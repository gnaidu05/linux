# Running quantlab 24/7

The service runs the scanner, a paper-traded strategy, the journal, and the
alert rules on a schedule, against live public market data. It is **paper
simulation only**: there is no broker account, no credential, and no code path
that could place an order. See [`../LIMITATIONS.md`](../LIMITATIONS.md) for what
the resulting numbers can and cannot support.

## Install

```bash
sudo ./install.sh
```

The script copies the package to `/opt/quantlab`, installs
`/etc/quantlab/config.json` (leaving an existing one alone), **runs one cycle to
verify it works before installing the unit**, then enables and starts
`quantlab.service`.

## Operate

```bash
systemctl status quantlab
journalctl -u quantlab -f          # live log
cat /var/lib/quantlab/status.json  # last cycle, paper equity, top scan
cat /var/lib/quantlab/health.json  # heartbeat: ok/failing, consecutive failures
systemctl restart quantlab         # safe: stops after the cycle in flight lands
```

State lives in `/var/lib/quantlab`, all of it plain JSON and JSONL:

| File | Contents |
|---|---|
| `status.json` | Last cycle: symbols, paper equity, journal summary, top scan, disclaimers |
| `health.json` | Heartbeat written every cycle, including failures |
| `scan_latest.json` | Latest ranking with each score's full component decomposition |
| `paper_state.json` | Paper cash, positions, and orders queued for the next bar |
| `paper_fills.jsonl` | Every simulated fill, append-only — this is what the journal reads |
| `paper_equity.jsonl` | Paper equity after each cycle that processed a bar |
| `alerts.jsonl` | Every alert fired, with the evidence behind it |
| `config_in_use.json` | The config the running process actually loaded |

## What "24/7" buys you, and what it does not

The loop wakes every `interval_seconds`, but it only does real work when a bar
has closed since the last cycle. At the default hourly bars with a five-minute
interval, eleven of every twelve cycles just refresh the heartbeat. Polling more
often does not produce more observations — the bar size and the calendar set
that.

The unit sets `Restart=always` and is enabled at boot, so the process survives
crashes and reboots. Within the process, a cycle that raises is logged and
backed off exponentially (capped at `max_backoff_seconds`) rather than exiting,
because the common failure — the venue being briefly unreachable — is one the
next cycle fixes by itself. `SIGTERM` and `SIGINT` stop the loop *after* the
cycle in flight finishes, so a restart never interrupts a state write.

`24/7` is literally true only for crypto, which is what the public feed covers.
Equities and FX have sessions and need a vendor API you configure yourself.

## Configuration

Edit `/etc/quantlab/config.json` and `systemctl restart quantlab`. Unknown keys
are rejected at load rather than ignored, so a typo fails loudly instead of
silently running defaults. See `config.example.json` for every key.

There is no field for an API key, a broker, or an account, because nothing in
the package could use one.

## Hardening

The unit runs under `DynamicUser=yes` with an empty `CapabilityBoundingSet`,
`ProtectSystem=strict`, `MemoryDenyWriteExecute=yes`, and a
`@system-service` syscall filter. `StateDirectory=quantlab` makes
`/var/lib/quantlab` the only path it can write. `RestrictAddressFamilies` limits
it to `AF_INET`/`AF_INET6` — enough for one outbound HTTPS GET and nothing else.

`systemd-analyze verify deploy/quantlab.service` passes clean.
