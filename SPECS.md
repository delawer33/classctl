# Technical Specification

## Centralized Management Software for Training Classrooms

---

### 1. Purpose

The software is intended for centralized execution of workstation preparation scripts on computers across multiple training classrooms. The target environment is in-person training conducted in several classrooms.

---

### 2. Operating Environment

**Workstations**

- Operating system: Linux
- Virtualization platform: VirtualBox
- Maximum number of machines per classroom: 35

**Network Infrastructure**

- IP addresses are assigned dynamically by a DHCP server
- Multiple classrooms are supported, each residing in its own subnet
- An existing network discovery script is used to retrieve the list of active machines (MAC and IP addresses)

**SSH Access**

- Authentication is exclusively via private key (password-based access is disabled)
- A single private key is shared across all machines in a given classroom
- Sudo privileges are embedded in the scripts themselves; explicit sudo invocation at call time is not required

---

### 3. Existing Scripts

**Location**

Default path: `/home/student/VBox_install`. The path must be configurable through the interface.

**Composition and Execution Order**

The execution order is strictly fixed (and we don't where they live):

1. Stop all virtual machines
2. Delete all virtual machines
3. Clear folders writable by students and reset the host machine to default settings
4. Create new virtual machines for the upcoming course
5. Shut down the host machine (optional, triggered on demand)

**Script Characteristics**

- Scripts produce diagnostic output to stdout/stderr during execution
- Exit codes are unreliable: a script may return zero even when an error has occurred
- Execution time: the longest script may run for up to 1.5 hours

---

### 4. Functional Requirements

**4.1 Classroom Configuration Management**

- Support for multiple classrooms, each with an independent configuration (subnet, machine list, script path, SSH key)
- Ability to add, edit, and delete classroom configurations

**4.2 Machine Discovery**

- Retrieval of the current machine list for a selected classroom via the built-in discovery script (MAC and IP addresses) (lies near this file, named `lan_ip.py`)

**4.3 Target Machine Selection**

- Execute operations on all machines in the selected classroom
- Execute operations on an arbitrary subset of machines, down to a single one

**4.4 Centralized Script Execution**

- Parallel SSH-based execution of scripts on all selected machines
- Strict adherence to the execution order defined in Section 3
- Progression to the next step only after the current step has completed on all target machines

**4.5 Wake-on-LAN**

- Power on machines via Wake-on-LAN using their MAC addresses before script execution begins
- After sending the WoL packet, wait for SSH to become available, then apply an additional ~60-second delay before launching scripts (to allow system services and VirtualBox to fully initialize)
- Handle cases where WoL is not supported at the BIOS level: notify the user and continue with the machines that are reachable

**4.6 Interfaces**

- Both a command-line interface (CLI) and a graphical user interface (GUI) are required
- Both interfaces must provide identical functionality and operate on a shared software core

**4.7 Execution Monitoring**

- Real-time display of execution status per machine (stdout/stderr output from scripts) — desirable, but not a hard requirement

**4.8 Logging**

- Logs are written only when errors occur
- No logging on successful completion (to preserve disk space)
- Since script exit codes are unreliable, the error detection strategy must be defined separately (output analysis, control markers, or post-execution state verification)

---

### 5. Non-Functional Requirements

- Support for up to 35 concurrent SSH sessions with long-running operations (up to 1.5 hours)
- Business logic must be decoupled from the presentation layer so that CLI and GUI share a common core
- Classroom configurations and script paths must persist between sessions

---

### 6. Documentation

The following documentation must be produced upon completion:

- User documentation
- Technical documentation

---

### 7. Open Questions Requiring Agreement

- Error detection strategy for scripts with unreliable exit codes
- Storage format and location for configurations (flat file, JSON, database, etc.)
- Whether user authentication is required to trigger operations via the GUI
