import sys
import re

def flatten_name(path, separator="_"):
    return separator.join(path)

def get_graph_id(path):
    raw_id = "__".join(path)
    safe_id = re.sub(r'[^a-zA-Z0-9_]', '_', raw_id)
    return safe_id

def resolve_target_path(current_path, target_str):
    if not target_str: return current_path 

    # 1. Absolute Path
    if target_str.startswith("/"):
        parts = target_str.strip("/").split("/")
        if parts[0] != "root": return ["root"] + parts
        return parts
    
    # 2. Legacy Absolute
    if target_str.startswith("root/"): 
        return target_str.split("/")
    
    # 3. Parent Relative (../)
    if target_str.startswith("../"):
        parent_scope = current_path[:-2]
        clean_target = target_str.replace("../", "")
        return parent_scope + clean_target.split("/")
    
    # 4. Current/Child Relative (./)
    if target_str.startswith("./"):
        if target_str == "./" or target_str == ".":
            return current_path
        clean_target = target_str[2:] 
        return current_path + clean_target.split("/")
    
    # 5. Sibling (Default)
    parent_scope = current_path[:-1]
    return parent_scope + target_str.split("/")

def resolve_state_data(root_data, path_parts):
    current = {'states': root_data.get('states', {}), 'initial': root_data.get('initial')}
    if path_parts == ['root']:
        return root_data
    
    start_idx = 1 if (path_parts and path_parts[0] == 'root') else 0
    
    for part in path_parts[start_idx:]:
        if 'states' not in current or part not in current['states']:
            return None
        current = current['states'][part]
    return current

def parse_fork_target(target_str):
    if target_str is None:
        return None, None
        
    match = re.match(r'(.*)/\[(.*)\]', target_str)
    if match:
        base = match.group(1)
        content = match.group(2)
        forks = [x.strip() for x in content.split(',')]
        return base, forks
    return target_str, None

def get_lca_index(source_path, target_path):
    lca_index = 0
    min_len = min(len(source_path), len(target_path))
    while lca_index < min_len:
        if source_path[lca_index] != target_path[lca_index]:
            break
        lca_index += 1
    if lca_index == len(source_path) and lca_index == len(target_path):
        lca_index -= 1
    return lca_index

def get_exit_sequence(source_path, target_path, func_formatter):
    lca_index = get_lca_index(source_path, target_path)
    exits = []
    for i in range(len(source_path) - 1, lca_index - 1, -1):
        state_segment = source_path[:i+1]
        func_name = func_formatter(state_segment)
        exits.append(func_name)
    return exits

def get_entry_sequence(source_path, target_path, func_formatter):
    lca_index = get_lca_index(source_path, target_path)
    if lca_index == len(target_path):
        lca_index -= 1

    entries = []
    for i in range(lca_index, len(target_path)):
        state_segment = target_path[:i+1]
        suffix = "_entry" if i == len(target_path) - 1 else "_start"
        func_name = func_formatter(state_segment, suffix)
        entries.append(func_name)
    return entries

# --- VISUALIZATION ---
def find_composites(name_path, data, result_set):
    my_id = get_graph_id(name_path)
    if 'states' in data:
        result_set.add(my_id)
        for child_name, child_data in data['states'].items():
            find_composites(name_path + [child_name], child_data, result_set)

def generate_dot_recursive(name_path, data, node_lines, edge_lines, composite_ids, decisions):
    my_id = get_graph_id(name_path)
    is_composite = 'states' in data
    indent = "    " * len(name_path)

    if is_composite:
        node_lines.append(f"{indent}subgraph cluster_{my_id} {{")
        node_lines.append(f"{indent}    label = \"{name_path[-1]}\";")
        
        # CHANGED: 'parallel' -> 'orthogonal'
        if data.get('orthogonal', False):
             node_lines.append(f"{indent}    style=dashed; color=black; penwidth=1.5; node [style=filled, fillcolor=white];")
             node_lines.append(f"{indent}    {my_id}_start [shape=point, width=0.15];")
             for child_name, child_data in data['states'].items():
                 child_path = name_path + [child_name]
                 child_id = get_graph_id(child_path)
                 tgt = f"{child_id}_start" if child_id in composite_ids else child_id
                 lhead = f"lhead=cluster_{child_id}" if child_id in composite_ids else ""
                 node_lines.append(f"{indent}    {my_id}_start -> {tgt} [style=dashed, {lhead}];")
        else:
             node_lines.append(f"{indent}    style=rounded; color=black; penwidth=1.0; node [style=filled, fillcolor=white];")
             if data.get('history', False):
                 node_lines.append(f"{indent}    {my_id}_hist [shape=circle, label=\"H\", width=0.3];")
             
             init_child_path = name_path + [data['initial']]
             init_child_id = get_graph_id(init_child_path)
             tgt = f"{init_child_id}_start" if init_child_id in composite_ids else init_child_id
             lhead = f"lhead=cluster_{init_child_id}" if init_child_id in composite_ids else ""
             node_lines.append(f"{indent}    {my_id}_start [shape=point, width=0.15];")
             node_lines.append(f"{indent}    {my_id}_start -> {tgt} [{lhead}];")

        for child_name, child_data in data['states'].items():
            generate_dot_recursive(name_path + [child_name], child_data, node_lines, edge_lines, composite_ids, decisions)
        node_lines.append(f"{indent}}}")
    else:
        label = name_path[-1]
        shape = "box"
        style = "rounded,filled"
        if data.get('decision', False):
            shape = "diamond"
            style = "filled"
            label = "" 
        node_lines.append(f"{indent}{my_id} [label=\"{label}\", shape={shape}, style=\"{style}\", fillcolor=white];")

    for t in data.get('transitions', []):
        target_str = t.get('to')
        
        if target_str is None or target_str == "null":
            # Termination node visualization could go here
            continue

        base_str, _ = parse_fork_target(target_str)
        
        is_decision = target_str in decisions
        target_path = resolve_target_path(name_path, base_str)
        target_id = get_graph_id(target_path)
        
        src = f"{my_id}_start" if is_composite else my_id
        ltail = f"ltail=cluster_{my_id}" if is_composite else ""
        
        if is_decision:
            tgt = get_graph_id(['root', target_str]) if target_str in decisions else target_str
            lhead = ""
        else:
            tgt = f"{target_id}_start" if target_id in composite_ids else target_id
            lhead = f"lhead=cluster_{target_id}" if target_id in composite_ids else ""

        attrs = [x for x in [ltail, lhead] if x]
        
        # CHANGED: Visualizing [Guard] / Action
        raw_guard = t.get('guard', '')
        raw_action = t.get('action', '')
        
        label_parts = []
        if raw_guard and raw_guard != True:
            label_parts.append(f"[{raw_guard}]")
        if raw_action:
            # Show abbreviated action if too long
            act_text = str(raw_action).strip().replace('\n', '; ')
            if len(act_text) > 15: act_text = act_text[:12] + "..."
            label_parts.append(f"/ {act_text}")
            
        safe_label = " ".join(label_parts).replace('"', '\\"')
        
        attrs.append(f'label="{safe_label}"')
        attrs.append('fontsize=10')
        edge_lines.append(f"{src} -> {tgt} [{', '.join(attrs)}];")

def generate_dot(root_data, decisions):
    composite_ids = set()
    find_composites(['root'], root_data, composite_ids)
    node_lines = []
    edge_lines = []
    generate_dot_recursive(['root'], root_data, node_lines, edge_lines, composite_ids, decisions)
    
    for name, transitions in decisions.items():
        dec_id = get_graph_id(['root', name])
        node_lines.append(f"    {dec_id} [label=\"?\", shape=diamond, style=filled, fillcolor=lightyellow];")
        for t in transitions:
            target_str = t.get('to')
            if target_str is None: continue
            
            base_str, _ = parse_fork_target(target_str)
            target_path = resolve_target_path(['root', name], base_str) 
            target_id = get_graph_id(target_path)
            tgt_node = f"{target_id}_start" if target_id in composite_ids else target_id
            lhead = f"lhead=cluster_{target_id}" if target_id in composite_ids else ""
            
            # Label logic for decisions
            raw_guard = t.get('guard', '')
            lbl = str(raw_guard).replace('"', '\\"')
            
            attr = f'label="{lbl}", fontsize=10'
            if lhead: attr += f", {lhead}"
            edge_lines.append(f"    {dec_id} -> {tgt_node} [{attr}];")

    lines = ["digraph StateMachine {", "    compound=true; fontname=\"Arial\"; node [fontname=\"Arial\"]; edge [fontname=\"Arial\"];"]
    lines.append("    // --- Structures ---")
    lines.extend(node_lines)
    lines.append("    // --- Transitions ---")
    lines.extend(edge_lines)
    lines.append("}")
    return "\n".join(lines)
