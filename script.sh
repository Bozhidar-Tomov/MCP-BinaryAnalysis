#!/usr/bin/env bash

#------------------------------------------------------------------------------
# script.sh - clone/update a list of public C repositories,
# compile every .c file found, disassemble the resulting object files and finally
# store the original C source together with the disassembly in a single JSON
# array.
#
# Requirements:
#   • bash ≥ 4 (for mapfile)
#   • git, gcc, objdump, jq, sed, find
#
# Output:
#   The JSON array is written to ${OUTFILE:-output.json}. Each element has the
#   form {"code": <stringified c file>, "assembly": <stringified objdump>}.
#------------------------------------------------------------------------------

set -euo pipefail

VERBOSE_INFO=false
VERBOSE_WARNING=false

WORKDIR="repos"
OUTFILE="output.json"

first_entry=true
processed_files=0
failed_files=0

REPOS=(
  "https://github.com/kokke/tiny-AES-c.git"
  "https://github.com/benhoyt/inih.git"
  "https://github.com/IanHarvey/minicrypt.git"
  "https://github.com/ultraembedded/fat_io_lib.git"
  "https://github.com/picolibc/picolibc.git"
  "https://github.com/brgl/uclibc-ng.git"
  "https://github.com/wolfssl/wolfssl.git"
  "https://github.com/Oryx-Embedded/CycloneCRYPTO.git"
  "https://github.com/embeddedartistry/libc.git"
  "https://github.com/singhofen/c-programming.git"
  "https://github.com/BilalGns/C-Examples.git"
  "https://github.com/DanielMartensson/C-Applications.git"
  "https://github.com/FreeRTOS/FreeRTOS-Kernel.git"
)

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --info|-i)
            VERBOSE_INFO=true
            shift
            ;;
        --warn|-w)
            VERBOSE_WARNING=true
            shift
            ;;
        --output|-o)
            if [[ -z "${2:-}" ]]; then
                log_error "Missing argument for --output"
                echo "Usage: $0 [--info|-i] [--warn|-w] [--output|-o FILE]"
                exit 1
            fi
            OUTFILE="$2"
            # removes the option and its value from the argument list
            shift 2
            ;;
        *)
            log_error "Unknown option: $1"
            echo "Usage: $0 [--info|-i] [--warn|-w] [--output|-o FILE]"
            exit 1
            ;;
    esac
done

# Check required tools
for cmd in git gcc objdump jq sed find; do
    if ! command -v $cmd &> /dev/null; then
        log_error "Required command '$cmd' not found."
        exit 1
    fi
done

log_info() {
    if [[ "$VERBOSE_INFO" = true ]]; then
        echo "[info] $1"
    fi
}

log_warning() {
    if [[ "$VERBOSE_WARNING" = true ]]; then
        echo "[WARNING] $1" >&2
    fi
}

log_error() {
    echo "[ERROR] $1" >&2
}

# Trap for cleanup
trap cleanup EXIT

# Cleanup function
cleanup() {
    local exit_code=$?
    if [[ $exit_code -ne 0 ]]; then
        log_error "Script failed with exit code $exit_code"
        
        if [[ -f "$OUTFILE" && $(tail -n 1 "$OUTFILE" | grep -v '^\]$') ]]; then
            log_warning "Fixing incomplete JSON output file"
            echo "]" >> "$OUTFILE"
        fi

    fi
    
    if [[ -d "$WORKDIR" ]]; then
        rm -rf "$WORKDIR" 2>/dev/null || log_error "Failed to remove working directory $WORKDIR"
    fi
    exit $exit_code
}

mkdir -p "$WORKDIR" || { log_error "Failed to create working directory $WORKDIR"; exit 1; }
> "$OUTFILE" || { log_error "Failed to create/truncate output file $OUTFILE"; exit 1; }

echo "[" > "$OUTFILE"

for repo in "${REPOS[@]}"; do
  reponame=$(basename "$repo" .git)
  repopath="$WORKDIR/$reponame"

  log_info "Cloning $repo..."
  rm -rf "$repopath" 2>/dev/null || log_warning "Failed to remove existing repo directory $repopath"
  if ! git clone --depth=1 "$repo" "$repopath" &>/dev/null; then
    log_error "Failed to clone $reponame, skipping"
    continue
  fi

  log_info "Searching for .c files in $reponame..."
  if ! mapfile -t cfiles < <(find "$repopath" -type f -name "*.c" 2>/dev/null); then
    log_error "Failed to find .c files in $reponame"
    continue
  fi
  
  if [[ ${#cfiles[@]} -eq 0 ]]; then
    log_warning "No .c files found in $reponame"
    continue
  fi

  for cfile in "${cfiles[@]}"; do
    # TODO: add a check to see if the file is already in the output file
    relname=$(basename "$cfile" .c)
    objfile="$WORKDIR/${relname}.o"

    log_info "Compiling $cfile..."
    if ! gcc -O0 -std=c17 -c -I"$repopath" "$cfile" -o "$objfile" 2>/dev/null; then
      log_warning "Failed to compile $cfile, skipping..."
      failed_files=$((failed_files+1))
      continue
    fi

    log_info "Disassembling $objfile..."
    [[ -f "$objfile" ]] || { log_error "Expected object file $objfile not found"; continue; }
    assembly=$(objdump -d -M intel "$objfile" 2>/dev/null | grep -v '^\s*$' | grep -v '^Disassembly' | grep -v '^$' | grep -v '^[[:space:]]*$' || echo "")
    
    if [[ -z "$assembly" ]]; then
      log_warning "No assembly generated for $objfile, skipping..."
      failed_files=$((failed_files+1))
      continue
    fi

    # Compress the original code by removing comments and empty lines
    if ! orig_code=$(cat "$cfile" 2>/dev/null | grep -v '^\s*\/\/' | grep -v '^\s*$' | sed 's/\/\*.*\*\///g'); then
      log_warning "Failed to process source code from $cfile, skipping..."
      failed_files=$((failed_files+1))
      continue
    fi
    
    if ! code_json=$(jq -Rs <<< "$orig_code" 2>/dev/null); then
      log_warning "Failed to convert source code to JSON for $cfile, skipping..."
      failed_files=$((failed_files+1))
      continue
    fi
    
    if ! asm_json=$(jq -Rs <<< "$assembly" 2>/dev/null); then
      log_warning "Failed to convert assembly to JSON for $objfile, skipping..."
      failed_files=$((failed_files+1))
      continue
    fi

    if [ "$first_entry" = true ]; then
      first_entry=false
    else
      echo "," >> "$OUTFILE" || { log_error "Failed to write to $OUTFILE"; exit 1; }
    fi

    if ! echo "  {\"code\": $code_json, \"assembly\": $asm_json}" >> "$OUTFILE"; then
      log_error "Failed to write JSON entry to $OUTFILE"
      exit 1
    fi
    
    processed_files=$((processed_files+1))
    log_info "Successfully processed $cfile"
    
    # Clean up object file
    rm -f "$objfile" 2>/dev/null || log_warning "Failed to remove temporary object file $objfile"
  done
done

echo "]" >> "$OUTFILE" || { log_error "Failed to finalize $OUTFILE"; exit 1; }
log_info "All done. Output written to $OUTFILE"
log_info "Successfully processed $processed_files files, $failed_files failed"