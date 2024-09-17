import asyncio
import os
import os.path

async def read_stream(stream, callback):
    while True:
        line = await stream.readline()

        if not line:
            break

        callback(line)

async def detect_input_request(process: asyncio.subprocess.Process, timeout=0.1):
    try:
        data = await asyncio.wait_for(process.stdout.read(1), timeout)
        return False, data.decode() if data else None
    except asyncio.TimeoutError:
        return True, None
    
async def detect_error(process: asyncio.subprocess.Process, timeout=0.1):
    try:
        data = await asyncio.wait_for(process.stderr.readline(), timeout)
        return data.decode()
    except asyncio.TimeoutError:
        return None

class PythonRunner:
    def __init__(self):
        self.code = ""
        self.session_id = ""
        self.is_running = False
        self.input_stack = []
        self.current_line = 0
        self.current_row = 0
        self.output_buffer = []
        self.error_buffer = []

    def set_code(self, code):
        self.code = code

    async def _run_python_code(self, code: str):
        temp_dir = os.path.join(os.getcwd(), "temp")
        session_dir = os.path.join(temp_dir, self.session_id)
        code_file_path = os.path.join(session_dir, "code.py")

        try:
            os.makedirs(temp_dir, exist_ok=True)
            os.makedirs(session_dir, exist_ok=True)

            with open(code_file_path, "w") as f:
                _ = f.write(code)

            # the code will be run in a separate process
            # since this will be an async generator since
            # this is streaming until the process is done.
            process = await asyncio.create_subprocess_exec(
                "python", code_file_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.PIPE,
                # run the code in the session directory
                cwd=session_dir,
                bufsize=0
            )

            last_input_requested = False
            
            def stdout_callback(line):
                self.output_buffer.append(line)

            def stderr_callback(line):
                self.error_buffer.append(line)

            stderr_task = asyncio.create_task(read_stream(process.stderr, stderr_callback))

            while True:
                if not last_input_requested:
                    if self.error_buffer:
                        error = self.error_buffer.pop(0).decode().strip()
                        yield ["error", error, self.pos()]
                        continue

                    if self.output_buffer:
                        output = self.output_buffer.pop(0).decode().strip()
                        yield ["output", output, self.pos()]
                        continue

                input_requested, output = await detect_input_request(process)
                if output:
                    yield ["output", output, self.pos()]

                if input_requested:
                    if self.input_stack:
                        input_data = self.input_stack.pop(0)
                        process.stdin.write(input_data.encode())
                        process.stdin.write(b"\n")
                        self.current_line += 1
                        self.current_row = 0
                        await process.stdin.drain()
                    elif not last_input_requested:
                        yield ["expecting_input", None, self.pos()]

                last_input_requested = input_requested
                if process.returncode is not None:
                    stdout_task = asyncio.create_task(read_stream(process.stdout, stdout_callback))

                    # Process has finished, but we need to ensure all output is read
                    await asyncio.gather(stdout_task, stderr_task)

                    # Yield any remaining output
                    while self.output_buffer:
                        output = self.output_buffer.pop(0).decode()
                        yield ["output", output, self.pos()]

                    while self.error_buffer:
                        error = self.error_buffer.pop(0).decode().strip()
                        yield ["error", error, self.pos()]

                    yield ["exit", process.returncode, self.pos()]
                    break

                await asyncio.sleep(0.01)  # Small delay to prevent busy waiting
        finally:
            # remove all the contents of the session directory
            for file in os.listdir(session_dir):
                os.remove(os.path.join(session_dir, file))
            os.rmdir(session_dir)


    def pos(self):
        return (self.current_line, self.current_row)
    
    def send(self, data: list):
        if data[0] == "output":
            if data[1] and isinstance(data[1], str) and data[1].endswith("\n"):
                self.current_line += 1
                self.current_row = 0
            else:
                self.current_row += 1
        elif data[0] == "error":
            self.current_line += 1
            self.current_row = 0
        return data

    async def run(self):
        self.is_running = True
        async for data in self._run_python_code(self.code):
            yield self.send(data)

    def input(self, data):
        print("Input received", data)
        self.input_stack.append(data)

if __name__ == "__main__":
    async def _run_in_background(runner: PythonRunner):
        async for data in runner.run():
            print(data)
            if data[0] == "exit":
                break
            elif data[0] == "output":
                # print(data[1], end="")
                continue
            elif data[0] == "expecting_input":
                data = input()
                runner.input(data)

    runner = PythonRunner()
    runner.set_code("name = input('Enter your name: ')\nprint('Hello', name)")
    asyncio.run(_run_in_background(runner))