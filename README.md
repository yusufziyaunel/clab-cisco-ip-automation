# Containerlab Cisco Automation
Python tool that automatically creates and configures network laboratories containing Cisco IOL and VIOS devices using Containerlab.

# Features
Create network topologies from a simple text file
Automatically configure Cisco IOL and VIOS devices
Assign loopback interfaces and IP addresses
Assign IP addresses for Router-Router and Router-Switch connections
Automatically save configurations

# Requirements

  * [Python 3.6+](https://www.python.org/downloads/)
  * [ContainerLab](https://containerlab.dev/)
  * [Ansible](https://docs.ansible.com/)
  * [Docker](https://www.docker.com/)
  * PyYaml(`pip install pyyaml`)
  * Cisco IOL Images
  * Cisoc IOSv Images

# Installation

1. Clone this repository:
<pre>
git clone https://github.com/network-automation/clab-cisco-ip-automation.git
cd clab-cisco-ip-automation
</pre>

4. Make the script executable:
chmod +x clab-cisco-ip-automation.py

5. Create your own input.txt with your topology:
<pre>
name: zamazingo
r1	e0/2	r2	e0/2
r1	e0/3	r3	e0/1
r2	e0/3	r3	e0/2
vr1	e0/2	vr2	e0/1
vr1	e0/1	vr3	e0/1
</pre>

# Usage
Run the script with:
<pre>
python3 clab-cisco-ip-automation.py
</pre>

# Workflow
The script will automatically perform the following operations:
Create a Containerlab YAML file
Deploy the lab
Enrich the Ansible inventory
Configure IOL and VIOS devices
Assign loopback interfaces and IP addresses
Save configurations

# File Structure
pylab.py: Main script
input.txt: Topology definition
config/: Configuration files for VIOS devices
clab-<lab_name>/: Directory created by Containerlab
clab-<lab_name>/ansible-inventory.yml: Ansible inventory file
clab-<lab_name>/host_vars/: Device configuration variables


# License
This project is licensed under the [MIT License](LICENSE).
