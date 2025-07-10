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
    code: str = Field(..., description="C source code string or path to a C source file")
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
    input: str = Field(..., description="Raw C source code, or path to a C source/object/executable file")
    is_source_code: bool = Field(True, description="Set to True if 'input' is C source code. Set to False if 'input' is a compiled object or executable file")
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
    - code: The C source code to compile either as code string or path to a C source file
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
        return CompileCOutput(success=False, error=str(ve)).model_dump()
    except Exception as e:
        if ctx: ctx.error(f"Unhandled error: {str(e)}")
        return CompileCOutput(success=False, error=str(e)).model_dump()

    if ctx and validated.verbose:
        ctx.info(f"Compiling C code with options: {validated.options}")

    # Detect if `code` is a path to an existing file and load its contents
    source_code = validated.code
    if os.path.exists(source_code):
        if ctx and validated.verbose:
            ctx.info(f"Reading C source from file: {source_code}")
        try:
            with open(source_code, "r", encoding="utf-8") as f:
                source_code = f.read()
        except Exception as e:
            if ctx: ctx.error(f"Failed to read source file: {e}")
            return CompileCOutput(success=False, error=str(e)).model_dump()

    opts = validated.options.split()
    try:
        cmd = ["gcc"] + opts + ["-xc", "-c", "-", "-o", validated.output_file]
        if ctx and validated.verbose:
            ctx.info(f"Running command: {' '.join(cmd)}")
        gcc = subprocess.run(
            cmd, text=True,
            input=source_code,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        
        if gcc.returncode:
            error_msg = gcc.stderr.strip()
            if ctx: ctx.error(f"GCC compilation error: {error_msg}")
            return CompileCOutput(success=False, error=error_msg, returncode=gcc.returncode).model_dump()
        return CompileCOutput(success=True, message=f"Successfully compiled to {validated.output_file}", stdout=gcc.stdout.strip(), output_file=validated.output_file).model_dump()
    except Exception as e:
        if ctx: ctx.error(f"Unhandled error: {str(e)}")
        return CompileCOutput(success=False, error=str(e)).model_dump()

@mcp.tool(
    name="disassemble_c",
    description="""
    Disassemble compiled object file or executable and return its assembly listing. If given C source code directly, it will first compile it using the compile_c tool and then disassemble.
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
        return DisassembleCOutput(success=False, error=str(ve), stage="validation").model_dump()
    object_file = None
    temp_file = None
    try:
        if validated.is_source_code:
            if ctx: ctx.info("Compiling C code before disassembly...")
            # Allow `input` to be either raw source code or a path to a .c file
            code_src = validated.input
            if os.path.exists(code_src):
                try:
                    with open(code_src, "r", encoding="utf-8") as f:
                        code_src = f.read()
                except Exception as e:
                    if ctx: ctx.error(f"Failed to read source file: {e}")
                    return DisassembleCOutput(success=False, error=str(e), stage="read_source").model_dump()
            temp_fd, temp_file = tempfile.mkstemp(suffix='.o')
            os.close(temp_fd)
            
            compile_result = compile_c(code_src, output_file=temp_file, options="-O0 -std=c17", ctx=ctx)
            if not compile_result.get("success"):
                error_msg = compile_result.get("error", "Unknown compilation error")
                if ctx: ctx.error(f"GCC compilation error: {error_msg}")
                return DisassembleCOutput(success=False, error=error_msg, stage="compilation").model_dump()
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
            return DisassembleCOutput(success=False, error=error_msg, stage="disassembly").model_dump()
        assembly = objdump.stdout.decode()
        return DisassembleCOutput(success=True, assembly=assembly).model_dump()
    except Exception as e:
        if ctx: ctx.error(f"Unhandled error: {str(e)}")
        return DisassembleCOutput(success=False, error=str(e)).model_dump()
    finally:
        if temp_file and os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except Exception:
                pass

@mcp.prompt()
def review_code(code: str | None = None, disassembly: str | None = None) -> list[base.Message]:
    """
    You are a security expert.
    You are given C source code and its disassembly in the conversation context (e.g., provided in earlier messages).
    Review the code and suggest fixes for vulnerabilities (memory leaks, overflows, underflows, zero-days, injections, etc.).
    Return a concise list of vulnerabilities and recommended fixes.
    The user should not need to re-upload the code or disassembly.
    """
    messages: list[base.Message] = [
        base.UserMessage(
            (
                "You are a proffesional application-security expert engineer with deep expertise in C and reverse-engineering.\n"
                "Carefully review the following C source code and its disassembly for security issues.\n"
                "Look for memory-safety bugs (buffer over/under-flows, use-after-free, double-free, leaks), "
                "integer issues, undefined behaviour, injections, race conditions, insecure APIs, and other common weaknesses.\n\n"

                "Perform the following steps:\n"
                "1. **Plan & Analyze** (internally, do not output):\n"
                "- Carefully review the code and disassembly for security issues.\n"
                "- Break the code into logical components (functions, modules, loops).\n"
                "- Identify data flows, API calls, memory allocations, and concurrency points.\n"
                "- Cross-reference disassembly addresses with source-line mappings to confirm control-flow.\n"
             
                "2. **Vulnerability Discovery Analysis and Review**:  \n"
                "- Focus on memory-safety (buffer overflows, use-after-free, double-free, integer overflow/underflow), undefined behavior, injection, insecure API use, race conditions, and other exploit primitives.  \n"
                "- Consider edge cases: unusual inputs, boundary values, error paths, and multi-thread interactions.\n"
                "- Cross-reference disassembly addresses with source-line mappings to confirm control-flow.\n"
                "- Consider any other relevant security issues even if they are not explicitly mentioned or obvious.\n"
                
                "For every vulnerability you find, provide the following in **Markdown**:\n"
                "3. **Output Findings** in a **numbered Markdown list**, with exactly these five fields:  \n"
                "   1. **Title** - brief, precise name (e.g. Heap-based buffer overflow in `parse_header()`).  \n"
                "   2. **Location** - function name and exact line numbers or address ranges.  \n"
                "   3. **Severity** - choose one: Low | Medium | High | Critical, and justify with CVSS-style reasoning.  \n"
                "   4. **Explanation** - clear description of root cause, how an attacker could trigger it, and impact.  \n"
                "   5. **Recommended Fix** - specific code changes, safer APIs, patches, or design adjustments.\n\n"
                "If no vulnerabilities are found, reply \"No vulnerabilities identified.\" "

                "Finish with any high-level hardening recommendations."
            )
        )
    ]
    if code:
        messages.append(base.UserMessage(code))
    if disassembly:
        messages.append(base.UserMessage(disassembly))
    messages.append(base.AssistantMessage("Below is the list of identified vulnerabilities and recommended fixes:"))
    return messages