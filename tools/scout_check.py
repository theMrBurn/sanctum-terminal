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
    console.print(
        Panel.fit(
            "[bold cyan]SANCTUM SCOUT PRE-FLIGHT[/bold cyan]", border_style="cyan"
        )
    )

    # Resolve the project root so we can find the /tests folder
    # We are in /tools, so root is one level up.
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    test_dir = os.path.join(root_dir, "tests")

    python_path = sys.executable
    git_path = get_bin("git")
    pmset_path = get_bin("pmset")

    # 1. Registry Sync Validation (Lab Manifest)
    console.print("[yellow]Checking Registry Sync...[/yellow]")
    manifest_path = os.path.join(root_dir, "config", "lab_manifest.json")
    if os.path.exists(manifest_path):
        console.print("[green] [✓] Registry Sync: Lab Manifest found.[/green]")
    else:
        console.print(
            "[red] [!] Registry Failure: config/lab_manifest.json missing.[/red]"
        )

    # 2. Logic Integrity Check (Updated for Modular Structure)
    console.print("[yellow]Executing Logic Audit...[/yellow]")
    # We set the PYTHONPATH to include the root so pytest can find 'src'
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{root_dir}:{env.get('PYTHONPATH', '')}"

    test_proc = subprocess.run(
        [python_path, "-m", "pytest", test_dir],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )  # nosec: B603

    if test_proc.returncode == 0:
        console.print("[green] [✓] Logic Verified: Vault is stable.[/green]")
    else:
        console.print("[red] [!] Logic Failure: Fix engine before scouting.[/red]")
        # Optional: Print pytest output if it fails to help debugging
        # console.print(test_proc.stdout)

    # 3. Safe Harbor Check
    console.print("[yellow]Checking Safe Harbor Status...[/yellow]")
    git_proc = subprocess.run(
        [git_path, "-C", root_dir, "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=False,
    )  # nosec: B603

    if not git_proc.stdout.strip():
        console.print("[green] [✓] Repository Clean: All progress committed.[/green]")
    else:
        console.print(
            "[red] [!] Uncommitted Changes: Safe Harbor is compromised.[/red]"
        )

    # 4. Environment Vitals
    console.print("[yellow]Checking System Vitals...[/yellow]")
    try:
        batt_proc = subprocess.run(
            [pmset_path, "-g", "batt"], capture_output=True, text=True, check=False
        )  # nosec: B603

        status = batt_proc.stdout.splitlines()[1].strip()
        console.print(f"[blue] [i] Energy Status: {status}[/i][/blue]")
    except (IndexError, AttributeError, FileNotFoundError):
        console.print("[blue] [i] Energy Status: External Power Connected[/i][/blue]")


if __name__ == "__main__":
    run_preflight()
