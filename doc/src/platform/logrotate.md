# Custom Logrotate Configuration { #nixos-logrotate }

logrotate is enabled on this machine and the service is automatically enabled for all service users. 

To rotate log files that are growing in service user directories, drop custom `logrotate.conf` snippets into `/etc/local/logrotate/{USER}`. You can put your application-specific logrotate snippets here and they will be executed regularly within the context of the owning user. 

Each service user must have a likewise named subdirectory, e.g.:
* `/etc/local/logrotate/s-myapp/myapp`
* `/etc/local/logrotate/s-otherapp/something`
* `/etc/local/logrotate/s-serviceuser/somethingelse`

!!! note
    If you store multiple files into this folders, **all** files will be activated.

### Global default options

We will apply the following basic options by default for user-defined logrotate config:

```text
daily
rotate 14
create
dateext
delaycompress
compress
notifempty
nomail
noolddir
missingok
sharedscripts
```
(Full details of these defaults are maintained in /etc/local/logrotate/README.txt)

### Understanding the Parameters
We deliberately keep our global defaults robust. For a full explanation of what parameters like dateext, missingok, or delaycompress do, or to see which other options you can use in your custom snippets, please refer directly to the official logrotate manual https://linux.die.net/man/8/logrotate or the logrotate GitHub project https://github.com/logrotate/logrotate.

### Example
Here's an example for a simple rotation signalling the owning process to re-open its file:
```bash
/srv/s-test/logs/*.log {
    rotate 5
    weekly

    postrotate
        kill -USR2 $(/srv/s-test/deployment/work/supervisor/bin/supervisorctl pid)
    endscript
}
```