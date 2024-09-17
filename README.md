# python-code-runner
A simple web server for running Python code snippets in the browser. Originally meant as a way to run python code snippets in Slidev presentations, but can be used in other web-based applications as well.

## Features
- Run python code snippets in the browser. 
- Fully interactive. The code snippet can take inputs and display outputs.
- Lightweight and easy to deploy.

## Usage
1. Clone the repository and create a virtual environment.
2. Install the dependencies using `pip install -r requirements.txt`.
3. Run the server using `python app.py`. This will start the server on `localhost:3480`.

### Usage via Slidev
To use the code runner in Slidev, add the following code snippet to your `setup/code-runners.ts` file:
```ts
import { defineCodeRunnersSetup, CodeRunnerContext, CodeRunnerOutput } from '@slidev/types'

async function executePythonCodeRemotely(code: string, ctx: CodeRunnerContext): Promise<CodeRunnerOutput> {
    const resp = await fetch(`$CODE_RUNNER_URL/run`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ 
            source: code,
            options: ctx.options
        }),
    });
    if (!resp.ok) {
        return {
            error: `Python code execution failed: ${resp.statusText}`,
        }
    }

    const data = await resp.text();
    const parser = new DOMParser();
    const doc = parser.parseFromString(data, 'text/html');
    const firstScript = doc.body.getElementsByTagName('python-runner-script')[0];
    if (!firstScript) {
        return {
            error: 'Python code execution failed: no output',
        }
    }

    // Create a script element with the content of the first script tag
    const script = doc.createElement('script');
    script.type = 'text/javascript';
    script.innerHTML = firstScript.innerHTML;

    return {
        element: script,
    }
}

export default defineCodeRunnersSetup(() => {
  return {
    python(code, ctx) {
      return executePythonCodeRemotely(code, ctx);
    },
  }
})
```
Learn more about Slidev code runners [here](https://sli.dev/custom/config-code-runners).

## API
The server has a single endpoint `/run` which accepts a POST request with the following JSON payload:
```json
{
    "code": "print('Hello, World!')",
    "options": {
        "inputs": ["Hello, World!"],
    }
}
```

The `code` field is the python code snippet to be executed. The `options` field is an optional field that can be used to provide inputs to the code snippet. The server will return an HTML response containing the JavaScript code for executing the code snippet and displaying the output.

## Security
There are no security measures in place, so be careful when deploying this server in a sensitive environment. The server will execute any Python code provided in the request, so make sure to submit trusted code only.

As for the HTML and JavaScript code returned in the `/run` response, the script tag is created as a custom HTML element (`python-runner-script`) as a way to bypass browser security restrictions. This is by design in order to run the code in use cases such as Slidev code runners. The code also contains instructions that generates and injects the HTML of the runner output where the script tag is located.

## Limitations
- It only supports single-file Python code snippets.
- It does not support external libraries or dependencies.
- It *may* not support long-running code snippets.
- It does not support terminal-specific texts like ANSI escape codes. (for now)

## Contributing
As this is only created for my own purpose, contributions are welcome! Feel free to open an issue or submit a pull request.

## License
This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Copyright
© 2024 [Ned Palacios](https://github.com/nedpals)