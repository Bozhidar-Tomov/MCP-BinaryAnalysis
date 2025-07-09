from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.prompts import base

import os
import json
import subprocess
import tempfile

# load examples from samples.json
samples_path = os.path.join(os.path.dirname(__file__), 'samples.json')

# create MCP server
mcp = FastMCP(
    name="c-tools",
    description="Tools for compiling C source code with GCC and disassembling it with objdump",
)

# load examples from samples.json
try:
    with open(samples_path, 'r') as f:
        _EXAMPLES = json.load(f)
except FileNotFoundError:
    _EXAMPLES = []

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
    name="compile_c",
    description="""
    Compile given C source code using GCC with specified options.
    Returns compilation output or errors.
    
    Parameters:
    - code: The C source code to compile (or a path to a .c file)
    - output_file: Name of the output file (default: output.o)
    - options: GCC compilation options (default: -O0 -std=c17)
    - verbose: Whether to include verbose output (default: False)
    """
)
def compile_c(code: str, output_file: str = "output.o", options: str = "-O0 -std=c17", verbose: bool = False, ctx=Context) -> dict:
    """Compile C code using GCC with specified options. Accepts code as a string or a file path."""
    import os
    # If code is a file path, read the file contents
    if os.path.isfile(code):
        with open(code, 'r') as f:
            code = f.read()
    
    if ctx is not None:
        ctx.info(f"Compiling C code to {output_file}...")
    
    # Parse options
    opts = options.split()
    
    try:
        # Base command
        cmd = ["gcc"] + opts + ["-xc", "-c", "-", "-o", output_file]
        
        if verbose and ctx is not None:
            ctx.info(f"Running command: {' '.join(cmd)}")
        
        # Run gcc
        gcc = subprocess.run(
            cmd,
            input=code.encode(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        
        # Handle results
        if gcc.returncode:
            error_msg = gcc.stderr.decode().strip()
            if ctx is not None:
                ctx.error(f"GCC compilation error: {error_msg}")
            
            return {
                "success": False,
                "error": error_msg,
                "returncode": gcc.returncode
            }
        
        return {
            "success": True,
            "message": f"Successfully compiled to {output_file}",
            "stdout": gcc.stdout.decode().strip(),
            "output_file": output_file
        }
        
    except Exception as e:
        if ctx is not None:
            ctx.error(f"Unhandled error: {str(e)}")
        
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool(
    name="disassemble_c",
    description="""
    Disassemble compiled object file or executable and return its assembly listing.
    If given C source code directly, it will first compile it and then disassemble.
    
    Parameters:
    - input: Either C source code, path to a .c file, or path to an object/executable file
    - is_source_code: Whether the input is C source code (default: True)
    - options: Objdump options (default: -d -M intel -S)
    """
)
def disassemble_c(input: str, is_source_code: bool = True, options: str = "-d -M intel -S", ctx=Context) -> dict:
    """Disassemble C code or object file and return assembly. Accepts code as a string or a file path."""
    import os
    object_file = None
    temp_file = None
    
    try:
        
        if is_source_code:
            if os.path.isfile(input) and input.endswith('.c'):
                with open(input, 'r') as f:
                    input = f.read()
            if ctx is not None:
                ctx.info("Compiling C code before disassembly...")
            
            
            temp_fd, temp_file = tempfile.mkstemp(suffix='.o')
            os.close(temp_fd)
            
            
            gcc = subprocess.run(
                ["gcc", "-O0", "-std=c17", "-xc", "-c", "-", "-o", temp_file],
                input=input.encode(),
                stderr=subprocess.PIPE,
            )
            
            if gcc.returncode:
                error_msg = gcc.stderr.decode().strip()
                if ctx is not None:
                    ctx.error(f"GCC compilation error: {error_msg}")
                
                return {
                    "success": False,
                    "error": error_msg,
                    "stage": "compilation"
                }
            
            object_file = temp_file
        else:
            
            object_file = input
            
        
        opts = options.split()
        
        
        if ctx is not None:
            ctx.info(f"Disassembling {object_file}...")
            
        objdump = subprocess.run(
            ["objdump"] + opts + [object_file],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        
        if objdump.returncode:
            error_msg = objdump.stderr.decode().strip()
            if ctx is not None:
                ctx.error(f"Objdump error: {error_msg}")
            
            return {
                "success": False,
                "error": error_msg,
                "stage": "disassembly"
            }
        
        assembly = objdump.stdout.decode()
        
        return {
            "success": True,
            "assembly": assembly
        }
        
    except Exception as e:
        if ctx is not None:
            ctx.error(f"Unhandled error: {str(e)}")
        
        return {
            "success": False,
            "error": str(e)
        }
    
    finally:
        # Clean up temporary file if created
        if temp_file and os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except:
                pass


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

if __name__ == "__main__":
    # For quick script usage: demonstrate both tools with ex1.c
    with open("ex1.c", "r") as f:
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