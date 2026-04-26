# UCS Traffic Monitoring (UTM)
Full-blown traffic monitoring of Cisco UCS servers using Grafana, InfluxDB and Telegraf.

PS: Please help decide UTM enhancements by these polls: https://github.com/paregupt/ucs_traffic_monitor/discussions

# Sister Projects
## Looking for something similar to monitor Cisco MDS Switches?
[Click here to check out MDS Traffic Monitoring (MTM)](https://github.com/paregupt/mds_traffic_monitor)

## Looking for something similar to monitor Cisco Nexus Switches?
[Click here to check out Nexus Traffic Monitoring (NTM)](https://github.com/paregupt/nexus_traffic_monitor)

# Use cases
Locations Dashboard
![enter image description here](https://www.since2k7.com/wp-content/uploads/2020/07/utm_0.4-1.png)

UCS Domains Overview
![enter image description here](https://www.since2k7.com/wp-content/uploads/2020/07/utm_0.4-3.png)

Top 10 ports, service profiles, etc.
![UTM_v0 6-overview](https://user-images.githubusercontent.com/8773072/122630893-12828d80-d07c-11eb-838c-c298e322e38d.gif)

Load Balance verification and root cause
![enter image description here](https://www.since2k7.com/wp-content/uploads/2020/07/utm_0.4-4.png)

Congestion Monitoring and detection 
![UTM_v0 6-congestion](https://user-images.githubusercontent.com/8773072/122630885-0696cb80-d07c-11eb-852b-dbc5f1722606.jpg)

End-to-end mapping from vHBA/vNIC to FI uplink Port
![enter image description here](https://www.since2k7.com/wp-content/uploads/2020/07/utm_0.4-8.png)

Integrated documentation with conceptual drawing and detailed explanations
![enter image description here](https://www.since2k7.com/wp-content/uploads/2020/07/utm_0.4-10.png)

Link utilization and errors
![UTM_v0 6-link-tabular-view](https://user-images.githubusercontent.com/8773072/122631083-b28ce680-d07d-11eb-8cc0-05d260fe6147.jpg)

and much more...

- **Data source**: [Cisco UCS Manager (UCSM)](https://www.cisco.com/c/en/us/products/servers-unified-computing/ucs-manager/index.html), read-only account is enough
- **Data receiver**: [Telegraf](https://github.com/influxdata/telegraf)
- **Data storage**: [InfluxDB](https://github.com/influxdata/influxdb), a time-series database
- **Visualization**: [Grafana](https://github.com/grafana/grafana)

# Installation
- Tested OS: CentOS 7.x. Should work on other OS also.
- Python version: Version 3 only. Should be able to work on Python 2 also with minor modification.

Two options:
- DIY Installation: Self install the required packages (or take a look to [ansible-install](ansible-install) folder where you could let the machine work for you)
- OVA - Required packages are pre-installed on CentOS 7.6 OVA

## DIY Installation
1. Install Telegraf
1. Install InfluxDB
1. Install Grafana. Install following plugins:
    1. Flowchart
    1. Pie Chart (using Pie chart v2 starting UTM v0.6)
    1. ePict panel (Not needed starting UTM v0.6)
    1. multistat (Not needed starting UTM v0.6)
1. Install following Python modules
    1. Cisco UCSM Python SDK
    1. netmiko library
    
## OVA installation
[Download OVA from releases page](https://github.com/paregupt/ucs_traffic_monitor/releases).
This is a CentOS 7.6 based OVA. Deployment is same as any other OVA that you have deployed before. [Click here for detailed installation instructions of the UTM OVA](https://www.since2k7.com/blog/2020/02/29/cisco-ucs-monitoring-using-grafana-influxdb-telegraf-utm-installation/#Installing_UTM_using_OVA). The OVA is based on v0.3. Upgrading to the latest must be your first step.

## Upgrades
You are responsible to upgrade Grafana, InfluxDB, Telegraf, Python and other packages. Upgrading UTM is simple with one or two commands and doesn't take more than a few minutes. Please refer to respective packages for upgrade process. Please keep a watch on the security vulnerabilities and fixes.

## Configuration

UCS Traffic Monitor reads credentials from environment variables (no
plaintext file is read at runtime).

### Required environment variables

```sh
# Comma-separated list of logical domain ids
UTM_DOMAINS=dom1,dom2

# Per-domain credentials
UTM_dom1_HOST=10.0.0.10
UTM_dom1_USER=monitoring
UTM_dom1_PASS=secret-password

# Optional grouping label (default: "default")
UTM_dom1_GROUP=production
```

### Recommended deployment

Place credentials in `/etc/utm/creds.env`:

```sh
sudo install -d -m 0700 -o telegraf -g telegraf /etc/utm
sudo install -m 0600 -o telegraf -g telegraf /dev/null /etc/utm/creds.env
sudo $EDITOR /etc/utm/creds.env
```

Use the provided `systemd/utm.service.example` and reference the env
file with `EnvironmentFile=/etc/utm/creds.env`.

For multi-instance deployments (previously `ucs_domains_group_1.txt` and
`ucs_domains_group_2.txt`), pass `--instance-name <name>` to keep log
files and pickle caches separate per instance.

### Telegraf exec input

```toml
[[inputs.exec]]
   interval = "60s"
   commands = [
       "python3 /usr/local/telegraf/ucs_traffic_monitor.py influxdb-lp --instance-name utm -vv",
   ]
   timeout = "50s"
   data_format = "influx"
```

When telegraf invokes the script, it inherits the environment from
its systemd unit. Add `EnvironmentFile=/etc/utm/creds.env` to the
telegraf systemd drop-in (or use a wrapper systemd service that
exports the vars before exec'ing telegraf).

### Migrating existing deployments

If you already have `ucs_domains_group_*.txt` files, use the migration
helper:

```sh
sudo python3 scripts/migrate_credentials.py \
    --input /etc/telegraf/ucs_domains_group_1.txt \
    --output /etc/utm/creds.env
sudo chown telegraf:telegraf /etc/utm/creds.env
sudo chmod 600 /etc/utm/creds.env
```

After validating the new deployment runs cleanly for 24-48h, securely
delete the legacy file:

```sh
sudo shred -u /etc/telegraf/ucs_domains_group_1.txt
```

also update the global values like

```shell
  logfile = "/var/log/telegraf/telegraf.log"
  logfile_rotation_max_size = "10MB"
  logfile_rotation_max_archives = 5
```
This should be able to 

 1. Pull metrics from UCS every 60 seconds
 2. Stitch them end-to-end between FI uplink ports and vNIC/vHBA on blade servers
 3. Write the data to InfluxDB

Import the [dashboards](https://github.com/paregupt/ucs_traffic_monitor/tree/master/grafana/dashboards) into Grafana. That's all. UTM should be fully functional.

For detailed steps-by-step instructions, especially if you do not have prior experience with Grafana, InfluxDB and Telegraf, check out: [Cisco UCS monitoring using Grafana, InfluxDB, Telegraf – UTM Installation](https://www.since2k7.com/blog/2020/02/29/cisco-ucs-monitoring-using-grafana-influxdb-telegraf-utm-installation/)


# Credits
- My wife (Dimple) and kids (Manan and Kiara) while I took away precious weekend hours from you and invested in the development of UTM.
- Folks in the Cisco UCS business unit and TAC, who knowingly or unknowingly helped me to build UTM and also for awesome content on ciscolive.com.
- Colleagues and friends in Cisco (Art, Craig, Eugene, Mark and a long list of people) for the inspiration. 
- End-users/customers: Philipe, Jason, Shawn, Ryan, Ian, and others for your great feedback.
