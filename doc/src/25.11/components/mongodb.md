---
search:
  exclude: true
---

!!! warning
    This is a sunsetting version of the platform documentation. Go to [the current version](../../platform-releases/fc-26.05-production/mongodb.md) for optimized support.

# MongoDB { #nixos-mongodb }

!!! warning
    The currently supported MongoDB
    versions are outdated and are only provided for the purpose of upgrading
    older machines to 25.05.

    New projects should not use MongoDB. As a replacement, we offer a
    [FerretDB role](../../platform-releases/fc-25.11-production/ferretdb.md#nixos-ferretdb) which is currently in beta.
    [FerretDB](https://www.ferretdb.com) builds on PostgreSQL and is compatible
    to MongoDB for many use cases.

Managed instance of [MongoDB](https://www.mongodb.com).
There's a role for each supported major version:

- mongodb32
- mongodb34
- mongodb36
- mongodb40
- mongodb42

## Configuration

MongoDB works out-of-the box without configuration.
You can put additional configuration in `/etc/local/mongodb/mongodb.yaml`.
It will be joined with the basic config.

## Command Line Interface

You can use the `mongo` Shell to query and update data as well
as perform administrative operations.

## Upgrade { #nixos-mongodb-upgrade }

!!! warning
    Upgrade paths must include all major versions: 3.2 -> 3.4 -> 3.6 -> 4.0 -> 4.2.
    Before each upgrade step, the feature compatibility version must be set to the
    current running mongodb version.

Set the compatibility version in the `mongo` Shell, for example:

```
db.adminCommand( { setFeatureCompatibilityVersion: "4.2" } )
```

To upgrade, disable the current role and enable the role for the next major version.
MongoDB will be upgraded and restarted on the next management task run.
This happens automatically after some time. You can trigger a rebuild with
`sudo fc-manage switch --update-enc` immediately.

The restart will fail if the feature compatibility version is too old ("error 62").
To fix this, go back to the last working role version, rebuild, and set the version.

## Monitoring

Our monitoring checks that the mongodb daemon is running and responds to requests.
