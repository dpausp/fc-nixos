---
global_sync_id: "v1"
---

# Support { #support-details }

We are happy to assist you with any issues that you may have when using our
services. We have multiple informal ways that you may be communicating with us
like telephone, chat, or video conferences.

However, for situations where a higher due diligence is required (like leaving
a paper trail of what we agreed on) we offer a formal support structure based
on an issue tracking system. You are always welcome to start inquiring about
any issue through our informal channels - our staff will guide you towards
the more formal structure if needed.

We differentiate inquiries into this system based on whether they critically
affect production services or not.


---

## General Support

For **non-critical issues**, general inquiries, or scheduled maintenance requests:

* **Channel:** Email [support@flyingcircus.io](mailto:support@flyingcircus.io)
* **Response Time:** Within 1 business day
* **Tracking:** Automatically opens a trackable ticket in our system.

---

## Emergency Support (SLA Customers)

Customers with an active **Service Level Agreement (SLA)** have access to additional ways of communication that will ensure that our personnel responds within the agreed short time frames (i.e. 24/7 and 1h response time) during an emergency.

!!! danger "**What qualifies as an emergency?**"
	
	Any incident resulting in large visible outages, blocked active development, or other severe business-adverse impacts directly caused by or related to our services.

In an emergency, we immediately reprioritize internal work to focus all required resources on resolving the incident. Live updates during large-scale outages are published on our **[Status Page](https://status.flyingcircus.io/){:target="_blank"}**.

---

### How Emergencies Are Triggered

An incident ticket is created automatically regardless of how the emergency is reported.

| Channel | Method | Details & Instructions |
| :--- | :--- | :--- |
| **Automated Alert** | Internal Monitoring | Outages detected by our monitoring system alert our engineers instantly. |
| **Emergency Email** | `emergency+<PIN>@flyingcircus.io` | Append your client-specific PIN (e.g., `emergency+1234@flyingcircus.io`). |
| **Emergency Hotline** | **+49 345 95990625** | Call and enter your client PIN when prompted. |

!!! note "Incident Alerting Channels"
    When an emergency ticket is created the active supporters are immediately
    notified via

    - Pushover (<https://pushover.net/>),
    - Pager (<http://www.ecityruf.de/>) and
    - Email

### Hotline Procedure
1. Your call is automatically routed to the on-duty engineer.
2. The engineer will pick up immediately or return your call within your SLA response window.
3. If caller ID is withheld, the engineer will contact your registered emergency contacts instead.


!!! warning "Standby Availability Hours"
    The standby support is *only* notified during the hours booked
    according to the SLA.
---

## Chat
For daily communication in ongoing projects we also offer the opportunity to chat with us. We decided to base our system upon the Matrix-protocol by hosting our own homeserver for every of our users. We do also provide a self-hosted and pre-configurated version of Element to allow easy access. However, alternative clients are allowed and welcomed to use.

We usually create a project-specific Matrix channel and invite all needed persons to join. You may participate using the Matrix ID provided by us, or your currently existing ID at any other homeserver of your choice. In this case: Just let us know how we can reach you.

If you want to use our Matrix setup, our pre-configured Element is available at [chat.flyingcircus.io](https://chat.flyingcircus.io).

There's a number of alternatives to the web version of Element available. An overview can be found at [matrix.org/ecosystem/clients](https://matrix.org/ecosystem/clients). Please make sure to use a client that's actively developed and supports end-to-end encryption (E2EE).

If you want to use your own client, please find the needed information below:

| Parameter | Value |
| :--- | :--- |
| **Homeserver** | `customermatrix.flyingcircus.io` |
| **Login** | `<your_flying_circus_username>` |
| **Password** | `<your_flying_circus_password>` |
| **Matrix handle** | `@<username>:my.flyingcircus.io` |

---

## Shared screen sessions

The multiuser session feature of GNU screen comes handy if a user needs remote assistance. Multiuser sessions allow other users to join in a running screen session. They see the same terminal output as the inviting user and are able to type in commands.

### Walk-through

We illustrate how to use it with an example. Imaging user alice has a screen session running and wants to invite user bob.  
We assume that alice is already running a screen session.

1. User **alice** needs to activate multiuser mode by typing:
   ++control+a++ `:multiuser on`
2. User **alice** needs to allow bob to join by typing:
   ++control+a++ `:acladd bob`
3. User **bob** joins the screen session by invoking at the shell:
   `bash
   screen -r alice/
   `
4. To detach from the shared session, bob types:
++control+a++ d

Both alice and bob should share the same terminal now. For further details, please refer to the screen(1) manual page.

### Limitations
!!! warning "Limitations"
	`screen` cannot be run inside `sudo` sessions. So start screen first and then sudo inside the screen session.