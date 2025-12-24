---
name: spec-workflow
description: Use the spec workflow tools to propose/apply/seal writing specs safely.
---

# Spec workflow

Use the spec tools as a closed loop:

1) Inspect: `spec__query`, `spec__get`  
2) Propose: `spec__propose` (generate a diff/proposal record)  
3) Apply: `spec__apply` (requires approval)  
4) Seal: `spec__seal` (requires approval; creates snapshot + read-only state)  

Notes:
- When spec is sealed, do not modify `spec/` via generic file tools. Use the spec workflow.
