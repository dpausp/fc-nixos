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

## General Support

For non-production critical issues please contact our support by sending an
email to <mailto:support@flyingcircus.io>. This will create a ticket and our staff will
follow up with you within at most a business day.

## Emergency Support

As a customer with a service level agreement you have access to additional ways
of communication that will ensure that our personnel responds within the agreed
short time frames (i.e. 24/7 and 1h response time) during an emergency.

An emergency is any situation where you experience large visible outages,
are unable to proceed with development, or find yourselve in any other
business-adverse situations caused by or related to our services.

In the case of an emergency we will concentrate our resources towards a
resolution. Other work is postponed until the problem is resolved. Information
about ongoing large scale emergencies and disruptive work is published on our
[status page](http://status.flyingcircus.io/).

There are three ways for us to get aware of an emergency:

- Our system monitoring detects an outage and alerts us automatically.

- You send an email to emergency+\<PIN>@flyingcircus.io (If your PIN is
  `1234`, send an email to `emergency+1234@flyingcircus.io`).

- You call our emergency support number *+49 345 95990625* and enter your
  client-specific PIN.

  The call is forwarded to on-duty supporter who either picks up
  immediately or will call you back within the allowed time frame of the SLA.
  If you phone number is not transmitted, our supporter will follow up with
  known emergency contacts from your team.

In any case there will be a support ticket created automatically.

!!! warning
    The standby support is *only* notified during the hours booked
    according to the SLA.

!!! note
    When an emergency ticket is created the active supporters are immediately
    notified via

    - Pushover (<https://pushover.net/>),
    - Pager (<http://www.ecityruf.de/>) and
    - Email.

## Chat { #chat }

For daily communication in ongoing projects we also offer the opportunity to chat with us.
We decided to base our system upon the Matrix-protocol by hosting our own homeserver for every of our users. We do also provide a self-hosted and pre-configurated version of Element to allow easy access. However, alternative clients are allowed and welcomed to use.

We usually create a project-specific Matrix channel and invite all needed persons to join. You may participate using the Matrix ID provided by us, or your currently existing ID at any other homeserver of your choice. In this case: Just let us know how we can reach you.

If you want to use our Matrix setup, our pre-configured Element is available at [chat.flyingcircus.io](https://chat.flyingcircus.io).

There's a number of alternatives to the web version of Element available. An overview can be found at [matrix.org/ecosystem/clients](https://matrix.org/ecosystem/clients/).
Please make sure to use a client that's actively developed and supports end-to-end encryption (E2EE).

If you want to use your own client, please find the needed information below:

Homeserver
: `customermatrix.flyingcircus.io`

Login
: `<your_flying_circus_username>`

Password
: `<your_flying_circus_password>`

Matrix handle
: `@<username>:my.flyingcircus.io`

## Shared screen sessions { #screen-multiuser }

The multiuser session feature of GNU `screen` comes handy if a user
needs remote assistance. Multiuser sessions allow other users to join in a
running screen session. They see the same terminal output as the inviting user
and are able to type in commands.

### Walk-through

We illustrate how to use it with an example. Imaging user `alice` has a screen
session running and wants to invite user `bob`.

We assume that `alice` is already running a screen session.

1. User `alice` needs to activate multiuser mode by typing
   ++Control-a :multiuser on<Return>++.
2. User `alice` needs to allow `bob` to join by typing ++Control-a :acladd    bob<Return>++.
3. User `bob` joins the screen session by invoking `screen -r    alice/` at the shell.
4. To detach from the shared session, bob types ++Control-a d++.

Both `alice` and `bob` should share the same terminal now. For further details,
please refer to the `screen(1)` manual page.

### Limitations

`screen` cannot be run inside `sudo` sessions. So start
screen first and then sudo inside the screen session.
