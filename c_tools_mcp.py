import os
import json
import subprocess
import tempfile
from typing import Optional
from pydantic import BaseModel, ValidationError, Field
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.prompts import base

# --- Pydantic Schemas ---
class CompileCInput(BaseModel):
    code: str
    output_file: str = Field("output.o", description="Name of the output file")
    options: str = Field("-O0 -std=c17", description="GCC compilation options")
    verbose: bool = Field(False, description="Verbose output")

class CompileCOutput(BaseModel):
    success: bool
    message: Optional[str] = None
    error: Optional[str] = None
    returncode: Optional[int] = None
    stdout: Optional[str] = None
    output_file: Optional[str] = None

class DisassembleCInput(BaseModel):
    input: str
    is_source_code: bool = Field(True, description="Is input C source code?")
    options: str = Field("-d -M intel -S", description="Objdump options")

class DisassembleCOutput(BaseModel):
    success: bool
    assembly: Optional[str] = None
    error: Optional[str] = None
    stage: Optional[str] = None

# --- MCP Server ---
mcp = FastMCP(
    name="c-tools",
    description="Tools for compiling C source code with GCC and disassembling it with objdump. Includes schema validation and agentic workflow hooks.",
)

# Load examples from context_samples/samples.json
samples_path = os.path.join(os.path.dirname(__file__), 'context_samples', 'samples.json')
try:
    with open(samples_path, 'r') as f:
        _EXAMPLES = json.load(f)
except FileNotFoundError:
    _EXAMPLES = []

@mcp.resource(
    uri="file:///context_samples/samples.json",
    name="disassembly_samples_resource",
    description="""
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
    """
    return _EXAMPLES

@mcp.tool(
    name="compile_c",
    description="""
    Compile given C source code using GCC with specified options. Returns compilation output or errors.
    Parameters:
    - code: The C source code to compile
    - output_file: Name of the output file (default: output.o)
    - options: GCC compilation options (default: -O0 -std=c17)
    - verbose: Whether to include verbose output (default: False)
    """
)
def compile_c(code: str, output_file: str = "output.o", options: str = "-O0 -std=c17", verbose: bool = False, ctx: Optional[Context] = None):
    """Compile C code using GCC with specified options and schema validation."""
    try:
        validated = CompileCInput(code=code, output_file=output_file, options=options, verbose=verbose)
    except ValidationError as ve:
        if ctx: ctx.error(f"Input validation error: {ve}")
        return CompileCOutput(success=False, error=str(ve)).dict()
    opts = validated.options.split()
    try:
        cmd = ["gcc"] + opts + ["-xc", "-c", "-", "-o", validated.output_file]
        if ctx and validated.verbose:
            ctx.info(f"Running command: {' '.join(cmd)}")
        gcc = subprocess.run(
            cmd,
            input=validated.code.encode(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if gcc.returncode:
            error_msg = gcc.stderr.decode().strip()
            if ctx: ctx.error(f"GCC compilation error: {error_msg}")
            return CompileCOutput(success=False, error=error_msg, returncode=gcc.returncode).dict()
        return CompileCOutput(success=True, message=f"Successfully compiled to {validated.output_file}", stdout=gcc.stdout.decode().strip(), output_file=validated.output_file).dict()
    except Exception as e:
        if ctx: ctx.error(f"Unhandled error: {str(e)}")
        return CompileCOutput(success=False, error=str(e)).dict()

@mcp.tool(
    name="disassemble_c",
    description="""
    Disassemble compiled object file or executable and return its assembly listing. If given C source code directly, it will first compile it and then disassemble.
    Parameters:
    - input: Either C source code or path to an object/executable file
    - is_source_code: Whether the input is C source code (default: True)
    - options: Objdump options (default: -d -M intel -S)
    """
)
def disassemble_c(input: str, is_source_code: bool = True, options: str = "-d -M intel -S", ctx: Optional[Context] = None):
    """Disassemble C code or object file and return assembly, with schema validation and agentic logging."""
    try:
        validated = DisassembleCInput(input=input, is_source_code=is_source_code, options=options)
    except ValidationError as ve:
        if ctx: ctx.error(f"Input validation error: {ve}")
        return DisassembleCOutput(success=False, error=str(ve), stage="validation").dict()
    object_file = None
    temp_file = None
    try:
        if validated.is_source_code:
            if ctx: ctx.info("Compiling C code before disassembly...")
            temp_fd, temp_file = tempfile.mkstemp(suffix='.o')
            os.close(temp_fd)
            gcc = subprocess.run(
                ["gcc", "-O0", "-std=c17", "-xc", "-c", "-", "-o", temp_file],
                input=validated.input.encode(),
                stderr=subprocess.PIPE,
            )
            if gcc.returncode:
                error_msg = gcc.stderr.decode().strip()
                if ctx: ctx.error(f"GCC compilation error: {error_msg}")
                return DisassembleCOutput(success=False, error=error_msg, stage="compilation").dict()
            object_file = temp_file
        else:
            object_file = validated.input
        opts = validated.options.split()
        if ctx: ctx.info(f"Disassembling {object_file}...")
        objdump = subprocess.run(
            ["objdump"] + opts + [object_file],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if objdump.returncode:
            error_msg = objdump.stderr.decode().strip()
            if ctx: ctx.error(f"Objdump error: {error_msg}")
            return DisassembleCOutput(success=False, error=error_msg, stage="disassembly").dict()
        assembly = objdump.stdout.decode()
        return DisassembleCOutput(success=True, assembly=assembly).dict()
    except Exception as e:
        if ctx: ctx.error(f"Unhandled error: {str(e)}")
        return DisassembleCOutput(success=False, error=str(e)).dict()
    finally:
        if temp_file and os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except Exception:
                pass

@mcp.prompt()
def review_code(code: str, disassembly: str) -> list[base.Message]:
    """
    You are a security expert.
    You are given a C code and its disassembly.
    Review the code and suggest fixes for vulnerabilities (memory leaks, overflows, underflows, zero-day, injection, etc).
    Return a list of vulnerabilities and fixes.
    """
    return [
        base.UserMessage("Review the code and suggest fixes for vulnerabilities."),
        base.UserMessage(code),
        base.UserMessage(disassembly),
        base.AssistantMessage(f"I've reviewed the code and found the following vulnerabilities:"),
    ]

if __name__ == "__main__":
    # For quick script usage: demonstrate both tools with example_files/ex1.c
    ex_path = os.path.join(os.path.dirname(__file__), "example_files", "ex1.c")
    with open(ex_path, "r") as f:
        code = f.read()
    try:
        print("=== Testing compile_c tool ===")
        compile_result = compile_c(code, ctx=None)
        print(f"Compilation result: {compile_result}")
        print("\n=== Testing disassemble_c tool ===")
        disassembly_result = disassemble_c(code, ctx=None)
        if disassembly_result["success"]:
            print("Disassembly successful. First 200 characters:")
            print(disassembly_result["assembly"][:200] + "...")
        else:
            print(f"Disassembly failed: {disassembly_result['error']}")
    except Exception as e:
        print(f"Error: {e}") 