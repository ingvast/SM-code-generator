import yaml
import sys
import argparse
import os

# Ensure we can import from local directory
sys.path.append(os.getcwd())

# Import the new parser helper
from codegen.common import generate_dot, resolve_target_path, flatten_name, parse_fork_target, resolve_state_data
from codegen.rust_lang import RustGenerator

class BuildError(Exception):
    pass

def collect_decisions(data):
    """Walk the state tree and collect all decisions: into a single flat dict.
    Merges with root-level decisions. Errors on duplicate names."""
    merged = dict(data.get('decisions', {}) or {})

    def walk(states):
        if not states:
            return
        for name, state_data in states.items():
            if not isinstance(state_data, dict):
                continue
            local = state_data.get('decisions')
            if local:
                for dname, dval in local.items():
                    if dname in merged:
                        print(f"\nERROR: Duplicate decision name '{dname}' found in state '{name}'.")
                        sys.exit(1)
                    merged[dname] = dval
                del state_data['decisions']
            walk(state_data.get('states'))

    walk(data.get('states'))
    data['decisions'] = merged

def get_state_data(root_data, path_parts):
    current = {'states': root_data.get('states', {}), 'initial': root_data.get('initial')}
    if path_parts == ['root']:
        return root_data
    start_idx = 1 if (path_parts and path_parts[0] == 'root') else 0
    for part in path_parts[start_idx:]:
        if 'states' not in current or part not in current['states']:
            return None
        current = current['states'][part]
    return current

def validate_model(data):
    print("Validating model...")
    errors = []
    
    def check_state(name_path, state_data):
        display_name = "/" + "/".join(name_path[1:])
        
        if 'states' in state_data:
            # CHANGED: Check 'orthogonal' instead of 'parallel'
            if 'initial' not in state_data and not state_data.get('orthogonal', False):
                errors.append(f"State '{display_name}' is composite but missing 'initial' property.")
            elif 'initial' in state_data:
                init = state_data['initial']
                if init not in state_data['states']:
                    errors.append(f"State '{display_name}' defines initial='{init}', but that child does not exist.")

        transitions = state_data.get('transitions', [])
        for i, t in enumerate(transitions):
            if 'to' not in t:
                errors.append(f"State '{display_name}', transition #{i+1}: Missing 'to'.")
                continue
            
            raw_target = t['to']

            if raw_target is None or raw_target == "null":
                continue

            if isinstance(raw_target, str) and raw_target.startswith('@'):
                decision_name = raw_target[1:]
                if decision_name not in data.get('decisions', {}):
                    errors.append(f"State '{display_name}', transition #{i+1}: Decision '@{decision_name}' does not exist.")
                continue

            base_target, forks = parse_fork_target(raw_target)
            
            target_path = resolve_target_path(name_path, base_target)
            target_obj = get_state_data(data, target_path)
            
            if target_obj is None:
                errors.append(f"State '{display_name}', transition #{i+1}: Target '{base_target}' (resolved: {'/'.join(target_path)}) does not exist.")
                continue 

            if forks:
                if 'states' not in target_obj:
                    errors.append(f"State '{display_name}': Fork target '{base_target}' is not a composite state.")
                else:
                    for fork in forks:
                        fork_parts = fork.split('/')
                        fork_abs_path = target_path + fork_parts
                        fork_obj = get_state_data(data, fork_abs_path)
                        if fork_obj is None:
                            errors.append(f"State '{display_name}': Fork branch '{fork}' does not exist inside '{base_target}'.")

        if 'states' in state_data:
            for child_name, child_data in state_data['states'].items():
                check_state(name_path + [child_name], child_data)

    if 'initial' not in data:
        errors.append("Root model missing 'initial' state.")
    else:
        if data['initial'] not in data['states']:
             errors.append(f"Root initial state '{data['initial']}' does not exist.")
    
    check_state(['root'], data)

    if errors:
        print("\n!!! VALIDATION ERRORS !!!")
        for e in errors:
            print(f"- {e}")
        print("-------------------------")
        sys.exit(1)
    print("Model OK.")

SUPPORTED_LANGS = ['c', 'rust']


def generate_lang(lang, data, output_base):
    """Generate code for a single language.

    Args:
        lang: Target language ('c', 'rust').
        data: Parsed YAML model.
        output_base: Full path without extension (e.g. '/tmp/statemachine').
    """
    basename = os.path.basename(output_base)

    if lang == 'c':
        from codegen.c_lang import CGenerator
        print("Generating C code...")
        gen = CGenerator(data, header_name=f"{basename}.h")
        header, source = gen.generate()
        h_path = output_base + ".h"
        c_path = output_base + ".c"
        with open(h_path, "w") as f: f.write(header)
        with open(c_path, "w") as f: f.write(source)
        print(f" -> {c_path} / .h created.")

    elif lang == 'rust':
        print("Generating Rust code...")
        gen = RustGenerator(data)
        source, _ = gen.generate()
        rs_path = output_base + ".rs"
        with open(rs_path, "w") as f: f.write(source)
        print(f" -> {rs_path} created.")

    else:
        print(f"WARNING: Unknown language '{lang}', skipping.")


def main():
    parser = argparse.ArgumentParser(description="State Machine Builder")
    parser.add_argument("file", help="Input YAML/SMB file")
    parser.add_argument("--lang", choices=SUPPORTED_LANGS, default=None,
                        help="Output language (default: read from 'lang' key in SMB file)")
    parser.add_argument("-o", "--output", default=None,
                        help="Output base path without extension (default: ./statemachine)")
    args = parser.parse_args()

    if not os.path.exists(args.file):
        sys.exit(f"Error: File '{args.file}' not found.")

    try:
        with open(args.file, 'r') as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        sys.exit(f"YAML Syntax Error: {e}")

    # Determine output base path
    if args.output:
        output_base = args.output
    else:
        output_base = os.path.join(".", "statemachine")

    # Ensure parent directory exists
    output_dir = os.path.dirname(output_base)
    if output_dir and not os.path.isdir(output_dir):
        os.makedirs(output_dir, exist_ok=True)

    # Determine which languages to generate
    if args.lang:
        languages = [args.lang]
    else:
        file_lang = data.get('lang', 'rust')
        if isinstance(file_lang, str):
            languages = [file_lang]
        else:
            languages = list(file_lang)

    for lang in languages:
        if lang not in SUPPORTED_LANGS:
            sys.exit(f"Error: Unsupported language '{lang}'. Supported: {', '.join(SUPPORTED_LANGS)}")

    collect_decisions(data)
    validate_model(data)

    decisions = data.get('decisions', {})

    try:
        print(f"Generating Graphviz DOT...")
        dot_content = generate_dot(data, decisions)
        dot_path = output_base + ".dot"
        with open(dot_path, "w") as f:
            f.write(dot_content)
        print(f" -> {dot_path} created.")

        for lang in languages:
            generate_lang(lang, data, output_base)

    except Exception as e:
        print(f"\nCRITICAL ERROR during generation: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
