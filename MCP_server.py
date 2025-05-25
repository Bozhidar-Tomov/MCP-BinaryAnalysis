from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.prompts import base

import os
import json
import subprocess

# load examples from samples.json
echo_examples_path = os.path.join(os.path.dirname(__file__), 'samples.json')

# create MCP server
mcp = FastMCP(
    name="c-disassembler",
    description="Compile C source code with GCC and disassemble it with objdump",
)

# load examples from samples.json
try:
    with open(echo_examples_path, 'r') as f:
        _EXAMPLES = json.load(f)
except FileNotFoundError:
    _EXAMPLES = []

# TODO: Return random batch of examples and add more examples
@mcp.resource(
    uri="file:///samples.json",
    name="disassembly_samples_resource",
    description=
    """
    Provides pre-loaded C examples and their disassembled outputs for priming the model to disassemble C.
    schema={
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "assembly": {"type": "string"}
            },
            "required": ["code", "assembly"]
        }
    }

    Return a list of sample mappings with 'code' and 'assembly' fields.
    """
) 
def disassembly_samples_resource():
    """
    Returns a list of sample mappings with 'code' and 'assembly' fields.
    These samples can be appended to AI context for reference.

    Return a list of sample mappings with 'code' and 'assembly' fields.
    """
    return _EXAMPLES


@mcp.tool(
    name="disassemble_c",
    description="""
    Compile given C source code and return its x86_64 assembly listing.
    Return a list of sample mappings with 'code' and 'assembly' fields.
    Send the code and assembly to the review_code prompt for review.
    Return the review results and the assembly.
    """
)
def disassemble_c(code: str, ctx=Context) -> str:
    ctx.info("Compiling C code...")
    try:
        gcc = subprocess.run(
            ["gcc", "-O0", "-std=c17", "-xc", "-c", "-", "-o", "out.o"],
            input=code.encode(),
            stderr=subprocess.PIPE,
        )
        if gcc.returncode:
            error_msg = gcc.stderr.decode().strip()
            if ctx is not None and hasattr(ctx, 'error'):
                ctx.error(f"GCC compilation error: {error_msg}. Suggest checking for missing includes or syntax errors.")
            raise RuntimeError(error_msg)

        ctx.info("Disassembling C code...")
        objdump = subprocess.run(
            ["objdump", "-d", "-M", "intel", "-S", "out.o"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if objdump.returncode:
            error_msg = objdump.stderr.decode().strip()
            if ctx is not None and hasattr(ctx, 'error'):
                ctx.error(f"Objdump error: {error_msg}. Suggest checking if the object file was created correctly.")
            raise RuntimeError(error_msg)

        return objdump.stdout.decode()
    except Exception as e:
        if ctx is not None and hasattr(ctx, 'error'):
            ctx.error(f"Unhandled error: {str(e)}. Suggest reviewing the C code for issues.")
        raise RuntimeError(str(e))
    

@mcp.prompt()
def review_code(code: str, disassembly: str) -> list[base.Message]:
    """
    You are a security expert.
    You are given a C code.
    You need to review the code and suggest fixes for vulnerabilities.
    You need to check for memory leaks, overflows, underflows, zero-day, injection and other issues.
    You need to check for security vulnerabilities in the code.
    
    Return a list of vulnerabilities and fixes.
    """

    return [
        base.UserMessage("Review the code and suggest fixes for vulnerabilities."),
        base.UserMessage(code),
        base.UserMessage(disassembly),
        base.AssistantMessage(f"I've reviewed the code and found the following vulnerabilities:"),
    ]

# command: mcp run C:\<FILE_PATH>\MCP_server.py