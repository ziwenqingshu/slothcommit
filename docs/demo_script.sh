#!/bin/bash
# Script used to record docs/demo.gif (asciinema rec -c docs/demo_script.sh, then agg).
# The repo it runs in is built by docs/demo_repo_steps.py; every commit in it was written by sloth.
export PATH=$HOME/.local/bin:$PATH
cd /tmp/demo/rec/gpa-calc
P=$'\e[1;32mzhixin\e[0m:\e[1;34m~/gpa-calc\e[0m$ '
type_run() {
  printf '%s' "$P"
  local s="$1"
  for ((i=0;i<${#s};i++)); do printf '%s' "${s:$i:1}"; sleep 0.035; done
  sleep 0.4; printf '\n'
  eval "$1"
  sleep "${2:-1.5}"
}
say() { printf '\e[2m# %s\e[0m\n' "$1"; sleep 1.2; }
say "11:40 pm. I just fixed a bug and have zero energy left to describe it."
type_run "git diff --cached --stat" 1.5
type_run "sloth commit -y" 2.5
say "Gemma 3 1B wrote that on a 2-vCPU box, offline. Now the weekly report for my advisor:"
type_run "sloth week --lang zh | head -n 6" 3
say "And if I'm too lazy to even type 'sloth':"
type_run "sloth hook install" 1
type_run "echo '- Grades: A, A-, B+ ... F' >> README.md && git add README.md" 0.5
type_run "git commit --no-edit" 2
type_run "git log --oneline | head -n 5" 3
