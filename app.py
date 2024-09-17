from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from runner import PythonRunner

import json
import asyncio
import os
import secrets
import html

SERVER_PORT = int(os.environ.get("PORT", "3480"))
BASE_URL = os.environ.get("BASE_URL", f"http://localhost:{SERVER_PORT}")

# base URL without the http:// or https://
BASE_URL_2 = BASE_URL.replace("http://", "//").replace("https://", "//")

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class RunCodeRequest(BaseModel):
    source: str
    options: dict = {}

def create_session_id():
    return secrets.token_urlsafe(16)

@app.post("/run")
async def run_code(request: RunCodeRequest):
    source_code = request.source
    source_escaped = json.dumps(source_code)
    session_id = create_session_id()
    output_id = f"runner-sandbox-output-{session_id}"
    session_id_quoted = f"\"{session_id}\""
    options_json = json.dumps(request.options)
    script_src = f"{BASE_URL}/runner.js"

    # Return an HTML with websocket connection and display the output
    return HTMLResponse(content="""<python-runner-script type=\"text/javascript\">
    var current = document.currentScript;
    var outputDiv = document.createElement("div");
    outputDiv.setAttribute("id", \""""+output_id+"""\");
    outputDiv.className = "runner-sandbox-output";
    current.parentElement.insertBefore(outputDiv, current);
    function _runCode() { window.startRunner("""+source_escaped+""", """+session_id_quoted+""", """+options_json+"""); }
    if (window.startRunner) {
        _runCode();
    } else {
        var script = document.createElement("script");
        script.src = '"""+script_src+"""';
        script.onload = _runCode;
        document.head.appendChild(script);
    }
</python-runner-script>""".strip())

@app.get("/runner.js")
async def get_runner_js():
    ws_endpoint = f"ws:{BASE_URL_2}/session"
    return Response(content="""function startRunner(sourceCode, sessionId, options = {}) {
    const runnerOutputId = `runner-sandbox-output-${sessionId}`;
    const runnerContainer = document.getElementById(runnerOutputId);
    const inputBuffer = [];
    const buf = [];
    let lastType = "output";
    let lastLine = 0;
                    
    if (options.inputs) {
        inputBuffer.push(...options.inputs);
    }

    function getLineElement(line, _type = "output") {
        let exists = true;
        let lineElement = runnerContainer.querySelector("#line-" + line);
        if (!lineElement) {
            exists = false;
            lineElement = document.createElement("div");
            lineElement.setAttribute("id", "line-" + line);
            lineElement.style.display = "flex";
            lineElement.style.alignItems = "items-center";
        }

        let preEl = lineElement.querySelector("pre." + _type);
        if (!preEl) {
            preEl = document.createElement("pre");
            preEl.textContent = "";
            preEl.className = _type;
            if (_type === "error") {
                preEl.style.color = "red";
            }       
            lineElement.appendChild(preEl);
        }

        if (!exists) {
            console.log("Appending line element", lineElement);
            runnerContainer.appendChild(lineElement);
        }

        return lineElement;
    }
                    
    function getLine(coords) { return coords[0] || 0; }

    const ws = new WebSocket(\"""" + ws_endpoint + """\");
    ws.onopen = function(event) {
        console.log("Connection opened");
        ws.send(JSON.stringify(["run", sourceCode, sessionId]));
    };

    function flushStdoutBuffer() {
        if (buf.length === 0) {
            return;
        }

        const lineElement = getLineElement(lastLine, lastType);
        console.log(lineElement);
        console.log("Flushing stdout buffer", lastLine, JSON.stringify(buf.join("")), sessionId, lineElement);
        const pre = lineElement.querySelector("pre." + lastType);
        pre.textContent += buf.join("");
        buf.splice(0, buf.length);
        lineElement.scrollIntoView();
    }

    ws.onmessage = function(event) {
        const data = JSON.parse(event.data);
        if (data[0] === "output" || data[0] === "error") {
            const line = getLine(data[2]);
            if (line !== lastLine || data[0] !== lastType) {
                flushStdoutBuffer();
            }

            buf.push(data[1]);
            lastLine = line;
            lastType = data[0];

            if (data[1].endsWith("\\n")) {
                flushStdoutBuffer();
            }
        } else if (data[0] === "expecting_input") {
            flushStdoutBuffer();

            if (inputBuffer.length > 0) {
                const input = inputBuffer.shift();
                ws.send(JSON.stringify(["input", input, sessionId]));
                buf.push(input+\"\\n\");
                return;
            }
            
            const line = getLine(data[2]);
            const lineElement = getLineElement(line);
            const input = document.createElement("input");
            input.type = "text";
            input.placeholder = "Enter input here";
            input.addEventListener("keydown", function(event) {
                if (event.key === "Enter") {
                    ws.send(JSON.stringify(["input", event.target.value, sessionId]));
                    event.target.disabled = true;
                    flushStdoutBuffer();
                }
            });

            lineElement.appendChild(input);
        } else if (data[0] === "exit") {
            flushStdoutBuffer();

            const returnCode = data[1];
            const line = getLine(data[2]);
            const lineElement = getLineElement(line, "exit");
            const pre = lineElement.querySelector("pre.exit");
            pre.style.color = returnCode === 0 ? "green" : "red";

            if (returnCode === 0) {
                pre.textContent = "Process exited successfully";
            } else {
                pre.textContent = "Process exited with an error (exit code: " + returnCode + ")";
            }

            ws.close();
        }
    }

    document.addEventListener("unload", function() {
        ws.close();
    });
};

window.startRunner = startRunner;""", media_type="text/javascript")

async def run_in_background(websocket: WebSocket, runner: PythonRunner):
    print("Running in background")
    async for data in runner.run():
        await websocket.send_json(data)

@app.websocket("/session")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()

    print("Websocket connection established")

    runner = PythonRunner()
    task = None

    try:
        while True:
            payload = await websocket.receive_json()
            print("Received payload", payload)

            command = payload[0]
            data: str = payload[1]

            if command == "run":
                data = html.unescape(data)
                session_id = payload[2]
                runner.session_id = session_id
                runner.set_code(data)

                print("Running code")
                task = asyncio.create_task(run_in_background(websocket, runner))
            elif command == "input":
                runner.input(data)
    except Exception as e:
        if task is not None:
            task.cancel()
        

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=SERVER_PORT, log_level="info")
