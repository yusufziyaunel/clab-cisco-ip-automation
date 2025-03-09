#!/usr/bin/env python3
import yaml
import subprocess
import time
import os

def parse_input_file(filename):
    # Input dosyasını oku
    with open(filename, 'r') as file:
        lines = file.readlines()
    # Lab ismini al
    lab_name = lines[0].split(': ')[1].strip()
    # Bağlantıları parse et
    connections = []
    for line in lines[1:]:
        parts = line.strip().split()
        if len(parts) == 4:
            connections.append({
                'device1': parts[0],
                'interface1': parts[1][1:],
                'device2': parts[2],
                'interface2': parts[3][1:]
            })
    return lab_name, connections

def create_yaml_structure(lab_name, connections):
    # Tüm benzersiz cihazları bul
    devices = set()
    for conn in connections:
        devices.add(conn['device1'])
        devices.add(conn['device2'])
    
    # YAML yapısını oluştur
    yaml_dict = {
        'name': lab_name,
        'topology': {
            'nodes': {},
            'links': []
        }
    }
    
    # Cihazları ekle
    for device in sorted(devices, key=lambda x: (x[0], int(x[1:]) if x[1:].isdigit() else int(x[2:]))):
        # Temel cihaz özellikleri
        device_config = {}
        
        # Cihaz tipini belirle
        if device.startswith('r'):
            # Normal router
            device_config['kind'] = 'cisco_iol'
            device_config['image'] = 'vrnetlab/cisco_iol:17.12.01'
            device_num = int(device[1:])
            device_config['mgmt-ipv4'] = f'172.20.20.{10 + device_num}'
        elif device.startswith('s'):
            # Normal switch
            device_config['kind'] = 'cisco_iol'
            device_config['image'] = 'vrnetlab/cisco_iol:L2-17.12.01'
            device_config['type'] = 'L2'
            device_num = int(device[1:])
            device_config['mgmt-ipv4'] = f'172.20.20.{100 + device_num}'
        elif device.startswith('vr'):
            device_config['kind'] = 'linux'
            device_config['image'] = 'vrnetlab/cisco_vios:15.9.3M6'
            device_config['binds'] = [f'config/{device}.cfg:/config/startup-config.cfg']
            device_num = int(device[2:])
            device_config['env'] = {'HOSTNAME': 'xrv'+ str(device_num)}
            device_config['mgmt-ipv4'] = f'172.20.20.{50 + device_num}'
        elif device.startswith('vs'):
            device_config['kind'] = 'linux'
            device_config['image'] = 'vrnetlab/cisco_viosl2:15.2.2020'
            device_config['type'] = 'L2'
            device_config['binds'] = [f'config/{device}.cfg:/config/startup-config.cfg']
            device_num = int(device[2:])
            device_config['env'] = {'HOSTNAME': 'viosl2-'+ str(device_num)}
            device_config['mgmt-ipv4'] = f'172.20.20.{150 + device_num}'
        
        yaml_dict['topology']['nodes'][device] = device_config
    
    # Bağlantıları ekle - Düzeltilmiş format
    for conn in connections:
        # Cihaz tipine göre interface formatını belirle
        if conn['device1'].startswith(('r', 's')):  # IOL cihazları için
            endpoint1 = f"{conn['device1']}:Ethernet{conn['interface1']}"
        else:  # VIOS cihazları için
            # VIOS için eth0/1 -> eth1 formatına dönüştür
            interface_num = conn['interface1'].replace('0/', '')
            endpoint1 = f"{conn['device1']}:eth{interface_num}"
            
        if conn['device2'].startswith(('r', 's')):  # IOL cihazları için
            endpoint2 = f"{conn['device2']}:Ethernet{conn['interface2']}"
        else:  # VIOS cihazları için
            # VIOS için eth0/1 -> eth1 formatına dönüştür
            interface_num = conn['interface2'].replace('0/', '')
            endpoint2 = f"{conn['device2']}:eth{interface_num}"
        
        # Endpoints'i doğrudan liste olarak ekle
        yaml_dict['topology']['links'].append({
            'endpoints': [endpoint1, endpoint2]
        })
    
    return yaml_dict

def write_yaml_file(yaml_dict, output_filename):
    # Custom representer for lists to format endpoints correctly
    def represent_list(self, data):
        # Check if this is an endpoints list
        if len(data) == 2 and all(isinstance(item, str) for item in data):
            # This is likely an endpoints list, format it as ["item1", "item2"]
            return self.represent_sequence('tag:yaml.org,2002:seq', data, flow_style=True)
        # Otherwise use default representation
        return self.represent_sequence('tag:yaml.org,2002:seq', data, flow_style=False)
    
    # Register the custom representer
    yaml.add_representer(list, represent_list, Dumper=yaml.Dumper)
    
    # YAML dosyasını oluştur
    with open(output_filename, 'w') as file:
        yaml.dump(yaml_dict, file, default_flow_style=False, sort_keys=False)


def enrich_inventory(inventory_path):
    # Mevcut inventory'yi oku
    with open(inventory_path, 'r') as file:
        inventory = yaml.safe_load(file)
    
    # Cisco IOL vars ekle
    if 'all' not in inventory:
        inventory['all'] = {}
    
    if 'children' not in inventory['all']:
        inventory['all']['children'] = {}
    
    # IOL cihazları için grup
    if 'cisco_iol' not in inventory['all']['children']:
        inventory['all']['children']['cisco_iol'] = {}
    
    if 'vars' not in inventory['all']['children']['cisco_iol']:
        inventory['all']['children']['cisco_iol']['vars'] = {}
    
    # IOL cihazları için parametreleri ekle
    inventory['all']['children']['cisco_iol']['vars'].update({
        'ansible_user': 'admin',
        'ansible_password': 'admin',
        'ansible_network_os': 'ios',
        'ansible_connection': 'network_cli',
        'ansible_become': True,
        'ansible_become_method': 'enable',
        'ansible_become_password': 'admin'
    })
    
    # VIOS cihazları için grup
    if 'cisco_vios' not in inventory['all']['children']:
        inventory['all']['children']['cisco_vios'] = {'hosts': {}}
    
    # Linux grubundan VIOS cihazlarını bul ve cisco_vios grubuna taşı
    if 'linux' in inventory['all']['children'] and 'hosts' in inventory['all']['children']['linux']:
        linux_hosts = inventory['all']['children']['linux']['hosts'].copy()
        for hostname, host_vars in linux_hosts.items():
            if 'vr' in hostname or 'vs' in hostname:
                # VIOS cihazını cisco_vios grubuna ekle
                inventory['all']['children']['cisco_vios']['hosts'][hostname] = host_vars
                # Linux grubundan çıkar
                del inventory['all']['children']['linux']['hosts'][hostname]
        
        # Linux grubu boş kaldıysa sil
        if not inventory['all']['children']['linux']['hosts']:
            del inventory['all']['children']['linux']
    
    # VIOS cihazları için parametreleri ekle
    if 'vars' not in inventory['all']['children']['cisco_vios']:
        inventory['all']['children']['cisco_vios']['vars'] = {}
    
    inventory['all']['children']['cisco_vios']['vars'].update({
        'ansible_user': 'admin',
        'ansible_password': 'admin',
        'ansible_network_os': 'ios',
        'ansible_connection': 'network_cli',
        'ansible_become': True,
        'ansible_become_method': 'enable',
        'ansible_become_password': 'admin',
        'ansible_ssh_common_args': '-o KexAlgorithms=+diffie-hellman-group1-sha1,diffie-hellman-group14-sha1,diffie-hellman-group-exchange-sha1 -o HostKeyAlgorithms=+ssh-rsa,ssh-dss'
    })
    
    # Global vars ekle
    if 'vars' not in inventory['all']:
        inventory['all']['vars'] = {}
    
    inventory['all']['vars']['ansible_httpapi_use_proxy'] = False
    
    # Güncellenmiş inventory'yi yaz
    with open(inventory_path, 'w') as file:
        yaml.dump(inventory, file, default_flow_style=False)

def create_loopback_playbooks():
    # IOL cihazları için loopback playbook
    iol_playbook = """---
- name: Configure Loopback Interfaces on IOL Devices
  hosts: cisco_iol
  gather_facts: false
  connection: network_cli
  tasks:
    - name: Get device number
      set_fact:
        device_number: "{{ inventory_hostname.split('-')[-1][1:] }}"
        device_type: "{{ inventory_hostname.split('-')[-1][0] }}"
      no_log: true
    
    - name: Configure Router Loopbacks
      ios_command:
        commands:
          - configure terminal
          - interface Loopback0
          - ip address 1.1.{{ device_number }}.1 255.255.255.255
          - no shutdown
          - interface Loopback10
          - ip address 172.16.{{ device_number }}.1 255.255.255.0
          - no shutdown
          - end
      when: device_type == 'r'
      register: router_config
    
    - name: Configure Switch Loopbacks
      ios_command:
        commands:
          - configure terminal
          - interface Loopback0
          - ip address 2.2.{{ device_number }}.1 255.255.255.255
          - no shutdown
          - interface Loopback10
          - ip address 172.17.{{ device_number }}.1 255.255.255.0
          - no shutdown
          - end
      when: device_type == 's'
      register: switch_config
    
    - name: Display Configuration Summary
      debug:
        msg: "{{ inventory_hostname.split('-')[-1] }} Loopback Yapılandırması:
              \\n- Loopback0: {{ '1.1.' if device_type == 'r' else '2.2.' }}{{ device_number }}.1/32
              \\n- Loopback10: {{ '172.16.' if device_type == 'r' else '172.17.' }}{{ device_number }}.1/24"
"""
    
    # VIOS cihazları için loopback playbook
    vios_playbook = """---
- name: Configure Loopback Interfaces on VIOS Devices
  hosts: cisco_vios
  gather_facts: false
  connection: network_cli
  tasks:
    - name: Get device number
      set_fact:
        device_number: "{{ inventory_hostname.split('-')[-1][2:] }}"
        device_type: "{{ inventory_hostname.split('-')[-1][0:2] }}"
      no_log: true
    
    - name: Configure Router Loopbacks
      ios_command:
        commands:
          - configure terminal
          - interface Loopback0
          - ip address 3.3.{{ device_number }}.1 255.255.255.255
          - no shutdown
          - interface Loopback10
          - ip address 172.18.{{ device_number }}.1 255.255.255.0
          - no shutdown
          - end
      when: device_type == 'vr'
      register: router_config
    
    - name: Configure Switch Loopbacks
      ios_command:
        commands:
          - configure terminal
          - interface Loopback0
          - ip address 4.4.{{ device_number }}.1 255.255.255.255
          - no shutdown
          - interface Loopback10
          - ip address 172.19.{{ device_number }}.1 255.255.255.0
          - no shutdown
          - end
      when: device_type == 'vs'
      register: switch_config
    
    - name: Display Configuration Summary
      debug:
        msg: "{{ inventory_hostname.split('-')[-1] }} Loopback Yapılandırması:
              \\n- Loopback0: {{ '3.3.' if device_type == 'vr' else '4.4.' }}{{ device_number }}.1/32
              \\n- Loopback10: {{ '172.18.' if device_type == 'vr' else '172.19.' }}{{ device_number }}.1/24"
"""
    
    # Playbook'ları kaydet
    with open('loopback_iol.yaml', 'w') as file:
        file.write(iol_playbook)
    
    with open('loopback_vios.yaml', 'w') as file:
        file.write(vios_playbook)
    
    # Ana playbook'u oluştur (her iki playbook'u çağıran)
    main_playbook = """---
- import_playbook: loopback_iol.yaml
- import_playbook: loopback_vios.yaml
"""
    
    with open('loopback.yaml', 'w') as file:
        file.write(main_playbook)

def create_interface_ip_playbooks():
    # IOL cihazları için interface IP playbook
    iol_playbook = """---
- name: Configure Interface IPs and Status on IOL Devices
  hosts: cisco_iol
  gather_facts: false
  connection: network_cli
  tasks:
    - name: Get device name
      set_fact:
        device_name: "{{ inventory_hostname.split('-')[-1] }}"
        is_router: "{{ inventory_hostname.split('-')[-1].startswith('r') }}"
      no_log: true
    # Switch'ler için tüm interface'leri etkinleştir
    - name: Enable all interfaces on switches
      cisco.ios.ios_interfaces:
        config:
          - name: "{{ item }}"
            enabled: true
        state: merged
      loop:
        - Ethernet0/0
        - Ethernet0/1
        - Ethernet0/2
        - Ethernet0/3
        - Ethernet1/0
        - Ethernet1/1
        - Ethernet1/2
        - Ethernet1/3
      when: not is_router
    # Router'lar için interface'leri yapılandır
    - name: Configure router interfaces
      block:
        - name: Enable interfaces
          cisco.ios.ios_interfaces:
            config:
              - name: "{{ item.name }}"
                enabled: true
            state: merged
          loop: "{{ interfaces }}"
          when: interfaces is defined
          
        - name: Configure IP addresses
          cisco.ios.ios_l3_interfaces:
            config:
              - name: "{{ item.name }}"
                ipv4:
                  - address: "{{ item.ip }}"
            state: merged
          loop: "{{ interfaces }}"
          when: interfaces is defined
      when: is_router
    # Yapılandırma sonuçlarını göster
    - name: Show router interface status
      block:
        - name: Get interface status
          ios_command:
            commands:
              - show ip interface brief | exclude unassigned
          register: if_status
        
        - name: Display interface summary
          debug:
            msg: |
              {{ device_name }} Interface Yapılandırması:
              {% for line in if_status.stdout_lines[0] %}
              {{ line }}
              {% endfor %}
      when: is_router
    - name: Show switch interface status
      block:
        - name: Get interface status
          ios_command:
            commands:
              - show interfaces status | include connected
          register: if_status
        
        - name: Display interface summary
          debug:
            msg: |
              {{ device_name }} Interface Durumu:
              {% for line in if_status.stdout_lines[0] %}
              {{ line }}
              {% endfor %}
      when: not is_router
"""
    
    # VIOS cihazları için interface IP playbook - GigabitEthernet formatını kullan
    vios_playbook = """---
- name: Configure Interface IPs and Status on VIOS Devices
  hosts: cisco_vios
  gather_facts: false
  connection: network_cli
  tasks:
    - name: Get device name
      set_fact:
        device_name: "{{ inventory_hostname.split('-')[-1] }}"
        is_router: "{{ inventory_hostname.split('-')[-1].startswith('vr') }}"
      no_log: true
    # Switch'ler için tüm interface'leri etkinleştir
    - name: Enable all interfaces on switches
      cisco.ios.ios_interfaces:
        config:
          - name: "{{ item }}"
            enabled: true
        state: merged
      loop:
        - GigabitEthernet0/0
        - GigabitEthernet0/1
        - GigabitEthernet0/2
        - GigabitEthernet0/3
      when: not is_router
    # Router'lar için interface'leri yapılandır
    - name: Configure router interfaces
      block:
        - name: Convert interface names
          set_fact:
            converted_interfaces: "{{ interfaces | map('combine', {'name': 'GigabitEthernet' + item.name.replace('eth', '0/') }) | list }}"
          loop: "{{ interfaces }}"
          when: interfaces is defined
          loop_control:
            label: "{{ item.name }}"
          register: conversion_result
          
        - name: Enable interfaces
          cisco.ios.ios_interfaces:
            config:
              - name: "{{ item.name }}"
                enabled: true
            state: merged
          loop: "{{ converted_interfaces }}"
          when: converted_interfaces is defined
          
        - name: Configure IP addresses
          cisco.ios.ios_l3_interfaces:
            config:
              - name: "{{ item.name }}"
                ipv4:
                  - address: "{{ item.ip }}"
            state: merged
          loop: "{{ converted_interfaces }}"
          when: converted_interfaces is defined
      when: is_router and interfaces is defined
    # Yapılandırma sonuçlarını göster
    - name: Show router interface status
      block:
        - name: Get interface status
          ios_command:
            commands:
              - show ip interface brief | exclude unassigned
          register: if_status
        
        - name: Display interface summary
          debug:
            msg: |
              {{ device_name }} Interface Yapılandırması:
              {% for line in if_status.stdout_lines[0] %}
              {{ line }}
              {% endfor %}
      when: is_router
    - name: Show switch interface status
      block:
        - name: Get interface status
          ios_command:
            commands:
              - show interfaces status | include connected
          register: if_status
        
        - name: Display interface summary
          debug:
            msg: |
              {{ device_name }} Interface Durumu:
              {% for line in if_status.stdout_lines[0] %}
              {{ line }}
              {% endfor %}
      when: not is_router
"""
    
    # Playbook'ları kaydet
    with open('interface_ip_iol.yaml', 'w') as file:
        file.write(iol_playbook)
    
    with open('interface_ip_vios.yaml', 'w') as file:
        file.write(vios_playbook)
    
    # Ana playbook'u oluştur (her iki playbook'u çağıran)
    main_playbook = """---
- import_playbook: interface_ip_iol.yaml
- import_playbook: interface_ip_vios.yaml
"""
    
    with open('interface_ip.yaml', 'w') as file:
        file.write(main_playbook)

def create_save_config_playbooks():
    # IOL ve VIOS cihazları için ortak save playbook
    save_playbook = """---
- name: Save Running Config to Startup Config
  hosts: cisco_iol:cisco_vios
  gather_facts: false
  connection: network_cli
  tasks:
    - name: Save configuration
      cli_command:
        command: copy running-config startup-config
        prompt: 'Destination filename \[startup-config\]'
        answer: "\r"
      register: output
      ignore_errors: yes
    - name: Display save output
      debug:
        var: output.stdout_lines
      when: output is defined"""
    
    # Save playbook'u kaydet
    with open('save_config.yaml', 'w') as file:
        file.write(save_playbook)

def save_iol_config(lab_name, inventory_path):
    save_playbook = """---
- name: Save Running Config to Startup Config for IOL Devices
  hosts: cisco_iol
  gather_facts: false
  connection: network_cli
  tasks:
    - name: Save configuration
      cli_command:
        command: copy running-config startup-config
        prompt: 'Destination filename \[startup-config\]'
        answer: "\r"
      register: output
      ignore_errors: yes
    - name: Display save output
      debug:
        var: output.stdout_lines
      when: output is defined"""
    
    # Save playbook'u kaydet
    with open('save_iol_config.yaml', 'w') as file:
        file.write(save_playbook)
    # Save playbook'u çalıştır
    print("\nKonfigürasyonlar kaydediliyor...")
    result = subprocess.run(
        ['ansible-playbook', '-i', inventory_path, 'save_iol_config.yaml'],
        capture_output=True, 
        text=True,
        env=dict(os.environ, ANSIBLE_DISPLAY_SKIPPED_HOSTS='false')
    )
    if result.returncode == 0:
        print("Konfigürasyonlar başarıyla kaydedildi")
        # Başarılı kayıt mesajlarını göster
        for line in result.stdout.split('\n'):
            if 'bytes copied' in line:
                print(line.strip())
    else:
        print("Konfigürasyon kaydetme sırasında hata oluştu:")
        if result.stderr:
            print(result.stderr)

def save_startup_config(lab_name, inventory_path):
    save_playbook = """---
- name: Save Running Config to Startup Config
  hosts: cisco_iol:cisco_vios
  gather_facts: false
  connection: network_cli
  tasks:
    - name: Save configuration
      cli_command:
        command: copy running-config startup-config
        prompt: 'Destination filename \[startup-config\]'
        answer: "\r"
      register: output
      ignore_errors: yes
    - name: Display save output
      debug:
        var: output.stdout_lines
      when: output is defined"""
    
    # Save playbook'u kaydet
    with open('save_config.yaml', 'w') as file:
        file.write(save_playbook)
    # Save playbook'u çalıştır
    print("\nKonfigürasyonlar kaydediliyor...")
    result = subprocess.run(
        ['ansible-playbook', '-i', inventory_path, 'save_config.yaml'],
        capture_output=True, 
        text=True,
        env=dict(os.environ, ANSIBLE_DISPLAY_SKIPPED_HOSTS='false')
    )
    if result.returncode == 0:
        print("Konfigürasyonlar başarıyla kaydedildi")
        # Başarılı kayıt mesajlarını göster
        for line in result.stdout.split('\n'):
            if 'bytes copied' in line:
                print(line.strip())
    else:
        print("Konfigürasyon kaydetme sırasında hata oluştu:")
        if result.stderr:
            print(result.stderr)
           
def create_network_vars(connections, lab_name):
    """Ağ yapılandırması için host_vars oluşturur"""
    class IPTracker:
        def __init__(self):
            self.used_subnets = set()
            self.switch_subnets = {}
            
        def get_ip_pair(self, r1, r2):
            # Router-Router bağlantıları için /30
            # Cihaz numaralarını al
            if r1.startswith('vr'):
                r1_num = 100 + int(r1[2:])  # vr1 -> 101, vr2 -> 102, ...
            else:
                r1_num = int(r1[1:])  # r1 -> 1, r2 -> 2, ...
                
            if r2.startswith('vr'):
                r2_num = 100 + int(r2[2:])  # vr1 -> 101, vr2 -> 102, ...
            else:
                r2_num = int(r2[1:])  # r1 -> 1, r2 -> 2, ...
            
            subnet = f"10.{r1_num}.{r2_num}.0"
            if subnet not in self.used_subnets:
                self.used_subnets.add(subnet)
                return f"10.{r1_num}.{r2_num}.1/30", f"10.{r1_num}.{r2_num}.2/30"
            return None, None
            
        def get_switch_subnet_ip(self, switch, router):
            # Switch ID'sini al
            if switch.startswith('vs'):
                switch_id = 100 + int(switch[2:])  # vs1 -> 101, vs2 -> 102, ...
            else:
                switch_id = int(switch[1:])  # s1 -> 1, s2 -> 2, ...
            
            if switch not in self.switch_subnets:
                # Switch ID'sine göre subnet bloğu oluştur
                self.switch_subnets[switch] = {
                    'subnet': f"192.168.{switch_id}.0/28",
                    'next_host': 1
                }
                                              
            # Bir sonraki kullanılabilir IP'yi al
            next_ip = self.switch_subnets[switch]['next_host']
            self.switch_subnets[switch]['next_host'] += 1
            
            # 192.168.switch_id.1, 192.168.switch_id.2, ... şeklinde IP'ler ata
            return f"192.168.{switch_id}.{next_ip}/28"
    
    ip_tracker = IPTracker()
    
    # Cihaz bazlı yapılandırma bilgilerini tut
    device_configs = {}
    
    # Önce switch bağlantılarını işle
    for conn in connections:
        if conn['device1'].startswith('s') or conn['device1'].startswith('vs') or conn['device2'].startswith('s') or conn['device2'].startswith('vs'):
            switch = conn['device1'] if conn['device1'].startswith('s') or conn['device1'].startswith('vs') else conn['device2']
            router = conn['device2'] if conn['device1'].startswith('s') or conn['device1'].startswith('vs') else conn['device1']
            
            # Router'ın r veya vr olduğunu kontrol et
            if router.startswith('r') or router.startswith('vr'):
                router_interface = conn['interface2'] if conn['device1'].startswith('s') or conn['device1'].startswith('vs') else conn['interface1']
                
                ip = ip_tracker.get_switch_subnet_ip(switch, router)
                
                # Router yapılandırmasını ekle
                if router not in device_configs:
                    device_configs[router] = {'interfaces': []}
                
                # Interface adını belirle
                if router.startswith('vr'):
                    # VIOS için eth formatını kullan
                    interface_num = router_interface.replace('0/', '')
                    interface_name = f"eth{interface_num}"
                else:
                    interface_name = f"Ethernet{router_interface}"
                
                device_configs[router]['interfaces'].append({
                    'name': interface_name,
                    'ip': ip,
                    'connected_to': switch
                })
    
    # Router-Router bağlantılarını işle
    for conn in connections:
        if (conn['device1'].startswith('r') or conn['device1'].startswith('vr')) and (conn['device2'].startswith('r') or conn['device2'].startswith('vr')):
            ip1, ip2 = ip_tracker.get_ip_pair(conn['device1'], conn['device2'])
            
            if ip1 and ip2:
                # İlk router yapılandırmasını ekle
                if conn['device1'] not in device_configs:
                    device_configs[conn['device1']] = {'interfaces': []}
                
                # Interface adını belirle
                if conn['device1'].startswith('vr'):
                    # VIOS için eth formatını kullan
                    interface_num = conn['interface1'].replace('0/', '')
                    interface_name1 = f"eth{interface_num}"
                else:
                    interface_name1 = f"Ethernet{conn['interface1']}"
                
                device_configs[conn['device1']]['interfaces'].append({
                    'name': interface_name1,
                    'ip': ip1,
                    'connected_to': conn['device2']
                })
                
                # İkinci router yapılandırmasını ekle
                if conn['device2'] not in device_configs:
                    device_configs[conn['device2']] = {'interfaces': []}
                
                # Interface adını belirle
                if conn['device2'].startswith('vr'):
                    # VIOS için eth formatını kullan
                    interface_num = conn['interface2'].replace('0/', '')
                    interface_name2 = f"eth{interface_num}"
                else:
                    interface_name2 = f"Ethernet{conn['interface2']}"
                
                device_configs[conn['device2']]['interfaces'].append({
                    'name': interface_name2,
                    'ip': ip2,
                    'connected_to': conn['device1']
                })
    
    # Switch'ler için boş yapılandırma ekle (sadece interface'leri aktif etmek için)
    for conn in connections:
        for device in [conn['device1'], conn['device2']]:
            if (device.startswith('s') or device.startswith('vs')) and device not in device_configs:
                device_configs[device] = {'interfaces': []}
    
    # Host vars dizinini oluştur
    host_vars_dir = f"clab-{lab_name}/host_vars"
    os.makedirs(host_vars_dir, exist_ok=True)
    
    # Her cihaz için host_vars dosyası oluştur
    for device, config in device_configs.items():
        with open(f"{host_vars_dir}/clab-{lab_name}-{device}.yml", 'w') as f:
            yaml.dump(config, f, default_flow_style=False)
    
    # Yapılandırma özetini göster
    print("\nYapılandırılacak interface IP'leri:")
    
    # Switch gruplarını göster
    switch_groups = {}
    for device, config in device_configs.items():
        if device.startswith('r') or device.startswith('vr'):
            for interface in config['interfaces']:
                if interface['connected_to'].startswith('s') or interface['connected_to'].startswith('vs'):
                    switch = interface['connected_to']
                    if switch not in switch_groups:
                        switch_groups[switch] = []
                    
                    # Interface adını düzelt
                    if device.startswith('vr'):
                        interface_name = interface['name'].replace('eth', '')
                    else:
                        interface_name = interface['name'].replace('Ethernet', '')
                    
                    switch_groups[switch].append({
                        'device': device,
                        'interface': interface_name,
                        'ip': interface['ip']
                    })
    
    print("\nSwitch grupları:")
    for switch, configs in sorted(switch_groups.items()):
        if switch.startswith('vs'):
            switch_id = 100 + int(switch[2:])
        else:
            switch_id = int(switch[1:])
        print(f"\n{switch} grubu (192.168.{switch_id}.0/28):")
        for config in sorted(configs, key=lambda x: x['device']):
            print(f"  {config['device']}({config['interface']}): {config['ip']}")
    
    # Router-Router bağlantılarını göster
    router_links = []
    for device, config in device_configs.items():
        if device.startswith('r') or device.startswith('vr'):
            for interface in config['interfaces']:
                if interface['connected_to'].startswith('r') or interface['connected_to'].startswith('vr'):
                    # Interface adını düzelt
                    if device.startswith('vr'):
                        interface_name = interface['name'].replace('eth', '')
                    else:
                        interface_name = interface['name'].replace('Ethernet', '')
                    
                    router_links.append({
                        'device1': device,
                        'interface1': interface_name,
                        'ip1': interface['ip'],
                        'device2': interface['connected_to'],
                    })
    
    print("\nRouter-Router bağlantıları:")
    processed_links = set()
    for link in sorted(router_links, key=lambda x: (x['device1'], x['device2'])):
        link_key = tuple(sorted([link['device1'], link['device2']]))
        if link_key not in processed_links:
            processed_links.add(link_key)
            # Karşı tarafın IP'sini bul
            for other_link in router_links:
                if other_link['device1'] == link['device2'] and other_link['device2'] == link['device1']:
                    print(f"  {link['device1']}({link['interface1']}) <-> "
                          f"{link['device2']}({other_link['interface1']}): "
                          f"{link['ip1']} - {other_link['ip1']}")
                    break
    
    return device_configs

def deploy_lab(yaml_file, lab_name, connections, reconfigure=False):
    try:
        # Config dizinini oluştur
        config_dir = "config"
        if not os.path.exists(config_dir):
            os.makedirs(config_dir)
            print(f"'{config_dir}' dizini oluşturuldu")
        
        # YAML dosyasını oku
        with open(yaml_file, 'r') as file:
            yaml_content = yaml.safe_load(file)
        
        # YAML dosyasını güncelle - vr ve vs cihazları için config yollarını değiştir
        for device_name, device_config in yaml_content['topology']['nodes'].items():
            if device_name.startswith('vr') or device_name.startswith('vs'):
                if 'binds' in device_config:
                    new_binds = []
                    for bind in device_config['binds']:
                        if '.cfg:' in bind:
                            # Yeni config yolu
                            cfg_file = f"{config_dir}/{device_name}.cfg"
                            new_bind = f"{cfg_file}:/config/startup-config.cfg"
                            new_binds.append(new_bind)
                            
                            # Dosya yoksa oluştur
                            if not os.path.exists(cfg_file):
                                print(f"Boş yapılandırma dosyası oluşturuluyor: {cfg_file}")
                                with open(cfg_file, 'w') as f:
                                    # Temel yapılandırma ekle
                                    f.write("hostname " + device_name + "\n")
                                    f.write("enable secret admin\n")
                                    f.write("username admin privilege 15 secret admin\n")
                                    f.write("line vty 0 4\n")
                                    f.write(" login local\n")
                        else:
                            new_binds.append(bind)
                    device_config['binds'] = new_binds
        
        # Güncellenmiş YAML dosyasını yaz
        with open(yaml_file, 'w') as file:
            yaml.dump(yaml_content, file, default_flow_style=False, sort_keys=False)
        
        # Containerlab deploy komutunu çalıştır
        if reconfigure:
            subprocess.run(['containerlab', 'deploy', '-t', yaml_file, '--reconfigure'], check=True)
        else:
            subprocess.run(['containerlab', 'deploy', '-t', yaml_file], check=True)
        
        print(f"Lab başarıyla deploy edildi: {lab_name}")
        
        # Inventory dosyasının oluşmasını bekle
        inventory_path = f"clab-{lab_name}/ansible-inventory.yml"
        max_attempts = 30
        attempt = 0
        while not os.path.exists(inventory_path) and attempt < max_attempts:
            time.sleep(1)
            attempt += 1
        
        if os.path.exists(inventory_path):
            # Inventory dosyasını zenginleştir
            print(f"Inventory dosyası bulundu: {inventory_path}")
            time.sleep(2)  # Dosyanın tamamen yazılmasını bekle
            enrich_inventory(inventory_path)
            print("Inventory dosyası zenginleştirildi")
            
            # Loopback playbook'u oluştur
            create_loopback_playbooks()
            print("Loopback playbook'ları oluşturuldu")
            
            # Interface IP playbook'u oluştur
            create_interface_ip_playbooks()
            print("Interface IP playbook'ları oluşturuldu")
            
            # Save config playbook'u oluştur
            create_save_config_playbooks()
            print("Save config playbook oluşturuldu")
            
            # Network yapılandırma değişkenlerini oluştur
            create_network_vars(connections, lab_name)
            print("Network yapılandırma değişkenleri oluşturuldu")
            
            # VIOS cihazları var mı kontrol et
            has_vios = False
            with open(inventory_path, 'r') as f:
                inv = yaml.safe_load(f)
                if 'cisco_vios' in inv['all']['children'] and 'hosts' in inv['all']['children']['cisco_vios']:
                    has_vios = True
            
            # Cihazların hazır olmasını bekle
            print("Cihazların hazır olması bekleniyor...")
            
            # IOL cihazları için bekleme
            max_attempts = 20
            for attempt in range(max_attempts):
                try:
                    # SSH bağlantısını test et - IOL cihazları için
                    result_iol = subprocess.run(
                        ['ansible', 'cisco_iol', '-i', inventory_path, '-m', 'ping'],
                        capture_output=True,
                        text=True
                    )
                    
                    if result_iol.returncode == 0:
                        print("IOL cihazları hazır!")
                        break
                    
                    print(f"Deneme {attempt + 1}/{max_attempts}... IOL cihazları henüz hazır değil.")
                    time.sleep(10)
                except Exception as e:
                    print(f"Ping sırasında hata: {e}")
                    time.sleep(10)
            
            # Loopback yapılandırmasını uygula - Sadece IOL cihazları için
            print("\nIOL cihazları için Loopback yapılandırması uygulanıyor...")
            print("-" * 50)
            result = subprocess.run(
                ['ansible-playbook', '-i', inventory_path, 'loopback_iol.yaml'],
                capture_output=True,
                text=True,
                env=dict(os.environ, ANSIBLE_DISPLAY_SKIPPED_HOSTS='false')
            )
            if result.returncode == 0:
                # Sadece yapılandırma özetini göster
                for line in result.stdout.split('\n'):
                    if "Loopback Yapılandırması" in line:
                        print(line.replace('\\n', '\n').replace('msg:', '').strip())
                print("-" * 50)
                print("IOL cihazları için Loopback yapılandırması başarıyla tamamlandı")
            else:
                print("Loopback yapılandırması sırasında hata oluştu:")
                print(result.stderr)
                
            # Interface IP'lerini yapılandır - Sadece IOL cihazları için
            print("\nIOL cihazları için Interface IP'leri yapılandırılıyor...")
            result = subprocess.run(
                ['ansible-playbook', '-i', inventory_path, 'interface_ip_iol.yaml'],
                capture_output=True,
                text=True,
                env=dict(os.environ, ANSIBLE_DISPLAY_SKIPPED_HOSTS='false')
            )
            
            # Interface IP çıktılarını işle
            if result.returncode == 0:
                print("\nIOL cihazları için Interface IP yapılandırması başarıyla tamamlandı")
                
                # Konfigürasyonu kaydet - Sadece IOL cihazları için
                print("\nIOL cihazları için konfigürasyonlar kaydediliyor...")
                save_iol_config(lab_name, inventory_path)
            else:
                print("\nInterface IP yapılandırması sırasında hata oluştu:")
                print(result.stderr)
            
            # VIOS cihazları için bilgilendirme mesajı
            if has_vios:
                print("\n" + "=" * 80)
                print("NOT: VIOS cihazları (vr1, vr2, vs1, vs2, ...) daha uzun sürede başlar.")
                print("Bu cihazlar için yapılandırma, cihazlar tamamen başladıktan sonra")
                print("aşağıdaki komutlarla manuel olarak yapılabilir:")
                print("\n# VIOS cihazları için Loopback yapılandırması:")
                print(f"ansible-playbook -i {inventory_path} loopback_vios.yaml")
                print("\n# VIOS cihazları için Interface IP yapılandırması:")
                print(f"ansible-playbook -i {inventory_path} interface_ip_vios.yaml")
                print("\n# VIOS cihazları için konfigürasyonları kaydetme:")
                print(f"ansible-playbook -i {inventory_path} save_config.yaml --limit cisco_vios")
                print("=" * 80)
        else:
            print("Inventory dosyası bulunamadı")
    except subprocess.CalledProcessError as e:
        print(f"Lab deploy edilirken hata oluştu: {e}")
    except Exception as e:
        print(f"Beklenmeyen bir hata oluştu: {e}")

def create_ansible_cfg():
    config = """[defaults]
connection = paramiko
host_key_checking = False
timeout = 60
deprecation_warnings = False
interpreter_python = auto_silent

[persistent_connection]
command_timeout = 60
connect_timeout = 60
"""
    with open('ansible.cfg', 'w') as file:
        file.write(config)

def main():
    # Ansible config dosyasını oluştur
    create_ansible_cfg()
   
    input_filename = 'input.txt'
    # Input dosyasını parse et
    lab_name, connections = parse_input_file(input_filename)
    # Output dosya adını lab isminden oluştur
    output_filename = f"{lab_name}.yaml"
    # YAML yapısını oluştur
    yaml_dict = create_yaml_structure(lab_name, connections)
    # YAML dosyasını yaz
    write_yaml_file(yaml_dict, output_filename)
    print(f"YAML dosyası başarıyla oluşturuldu: {output_filename}")
    
    # Lab'ı deploy et ve inventory'yi zenginleştir
    # Eğer lab zaten varsa, reconfigure=True ile çağırın
    deploy_lab(output_filename, lab_name, connections, reconfigure=False)

if __name__ == "__main__":
    main()
