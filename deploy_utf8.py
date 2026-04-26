import sys
import subprocess
import os

# Set environment variable for UTF-8
os.environ['PYTHONIOENCODING'] = 'utf-8'

# Run modal deploy with output suppression and error handling
try:
    result = subprocess.run(
        ["modal", "deploy", "modal_updated_complete.py"],
        capture_output=True,
        encoding='utf-8',
        errors='replace'
    )

    # Print ASCII-safe version of output
    safe_stdout = result.stdout.encode('ascii', errors='replace').decode('ascii')
    safe_stderr = result.stderr.encode('ascii', errors='replace').decode('ascii')

    print(safe_stdout)
    if safe_stderr:
        print(safe_stderr)

    if result.returncode == 0:
        print("\nDeployment successful!")
    else:
        print(f"\nDeployment failed with exit code {result.returncode}")

    sys.exit(result.returncode)
except Exception as e:
    print(f"Error during deployment: {e}")
    sys.exit(1)
