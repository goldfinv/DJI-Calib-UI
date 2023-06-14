import subprocess

# Define the list of models
models = [
    "A2", "P330", "P330V", "P330Z", "P330VP", "WM610", "P3X", "P3S", "MAT100", "P3C",
    "MG1", "WM325", "WM330", "MAT600", "WM220", "WM620", "WM331", "MAT200", "MG1S",
    "WM332", "WM100", "WM230", "WM335", "WM240", "WM245", "WM246", "WM160", "WM231",
    "WM232", "WM260"
]

# Get a list of available COM ports
result = subprocess.run(['wmic', 'path', 'Win32_SerialPort', 'Get', 'DeviceID', '/value'],
                        capture_output=True, text=True)
output = result.stdout.strip()
com_ports = [line.split('=')[1] for line in output.split('\n') if line.strip()]

# Check if any COM ports are available
if not com_ports:
    print("No COM ports available.")
    exit()

# Prompt user to select a COM port
print("Available COM Ports:")
for index, com_port in enumerate(com_ports, start=1):
    print(f"{index}. {com_port}")
selection = input("Select the COM port (enter the corresponding number): ")

# Validate the user's selection
if not selection.isdigit() or int(selection) < 1 or int(selection) > len(com_ports):
    print("Invalid selection. Please try again.")
    exit()

# Get the selected COM port from the list
com_port = com_ports[int(selection) - 1]

# Prompt user to select a model number
print("Available Models:")
for index, model in enumerate(models, start=1):
    print(f"{index}. {model}")
selection = input("Select the model number (enter the corresponding number): ")

# Validate the user's selection
if not selection.isdigit() or int(selection) < 1 or int(selection) > len(models):
    print("Invalid selection. Please try again.")
    exit()

# Get the selected model number from the list
model_num = models[int(selection) - 1]

# Define the commands
command1 = f"python comm_og_service_tool.py --port {com_port} {model_num} GimbalCalib JointCoarse"
command2 = f"python comm_og_service_tool.py --port {com_port} {model_num} GimbalCalib LinearHall"

# Execute command1 and capture the output
print(f"Running command 1: {command1}")
result1 = subprocess.run(command1, capture_output=True, text=True)
print(result1.stdout)

# Prompt for the second command
choice = input("Wait until Gimbal is done. Do you want to run the second command?\n1. YES\n2. NO\nEnter 1 for YES or 2 for NO: ")

if choice == "1":
    # Execute command2 and capture the output
    print(f"Running command 2: {command2}")
    result2 = subprocess.run(command2, capture_output=True, text=True)
    print(result2.stdout)
else:
    print("Second command skipped.")
