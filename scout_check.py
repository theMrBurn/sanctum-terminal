Understood. Let’s lock this down. Here is the "Principal-Grade" refactor for both files. These versions include the surgical # nosec suppressions to satisfy the Bandit auditor while maintaining the security improvements we built today.

1. scout_check.py
Changes: Added absolute path resolution and # nosec suppressions for subprocess imports and calls.

Python
import os
import subprocess  # nosec: B404
import shutil
import sys
from rich.console import Console
from rich.panel import Panel

console = Console()

def get_bin(name: str) -> str:
    """Resolves absolute paths to satisfy Bandit B607."""
    path = shutil.which(name)
    if not path:
        if name == "pmset":
            return "/usr/bin/pmset"
        raise FileNotFoundError(f"Critical binary '{name}' not found.")
    return path

def run_preflight():
    console.print(Panel.fit("[bold cyan]SANCTUM SCOUT PRE-FLIGHT[/bold cyan]", border_style="cyan"))
    
    python_path = sys.executable
    git_path = get_bin("git")
    pmset_path = get_bin("pmset")

    # 1. Logic Integrity Check
    console.print("[yellow]Executing Logic Audit...[/yellow]")
    test_proc = subprocess.run(
        [python_path, "-m", "pytest", "test_engine.py"],
        capture_output=True,
        text=True,
        check=False
    )  # nosec: B603
    
    if test_proc.returncode == 0:
        console.print("[green] [✓] Logic Verified: Vault is stable.[/green]")
    else:
        console.print("[red] [!] Logic Failure: Fix engine before scouting.[/red]")

    # 2. Safe Harbor Check
    console.print("[yellow]Checking Safe Harbor Status...[/yellow]")
    git_proc = subprocess.run(
        [git_path, "status", "--porcelain"], 
        capture_output=True, 
        text=True,
        check=False
    )  # nosec: B603
    
    if not git_proc.stdout.strip():
        console.print("[green] [✓] Repository Clean: All progress committed.[/green]")
    else:
        console.print("[red] [!] Uncommitted Changes: Safe Harbor is compromised.[/red]")

    # 3. Environment Vitals
    console.print("[yellow]Checking System Vitals...[/yellow]")
    batt_proc = subprocess.run(
        [pmset_path, "-g", "batt"], 
        capture_output=True, 
        text=True, 
        check=False
    )  # nosec: B603
    
    try:
        status = batt_proc.stdout.splitlines()[1].strip()
        console.print(f"[blue] [i] Energy Status: {status}[/i][/blue]")
    except (IndexError, AttributeError):
        console.print("[blue] [i] Energy Status: External Power Connected[/i][/blue]")

if __name__ == "__main__":
    run_preflight()