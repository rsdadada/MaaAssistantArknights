---
order: 99
icon: iconoir:developer
---

# Personal cultivation edition

This edition targets Windows x64 and the Chinese game client. Application and resource updates come from personal Releases in `rsdadada/MaaAssistantArknights`.

## First launch

Extract the complete package into a separate directory. To keep settings, close MAA and copy `config` and `data` from the previous installation; let the new edition create its own resource cache. Run `MAA.exe`, configure promotion, level, skill and mastery targets, enable material supply, and move cultivation before ordinary farming and inventory maintenance.

Plans run in list order. Closed stages, occupied training rooms and insufficient sanity defer a target until a later run. Inventory maintenance targets remain intact. Credit, vouchers and potions start disabled with zero allowances. Configure daily limits and reserve balances before enabling them. Vouchers purchase only chip catalysts; the expiring-only option uses potions expiring within two days. Originite Prime recovery is disabled. Allowances persist per profile and CN game day, including across restarts. Use `__experience` to override the total-experience farming source.

## Updates and failures

The first personal launch enables the beta channel and automatic downloading/installing; subsequent launches retain preferences. Beta also receives final releases. Packages must match personal release metadata. Resource caches are tied to compatible application builds; old official caches are not loaded.

Dedicated live cultivation testing was not performed. Builds, configuration, supply planning and offline checks are covered; gameplay is validated through ordinary use. Uncertain recognition stops the affected action and records the reason.

## Maintenance

`.github/workflows/personal-release.yml` checks every six hours and supports manual dispatch. Settings live in `personal/release-config.json`; patch order is in `personal/patches/series`. The repository variable `PERSONAL_PUBLISH_ENABLED=true` enables publishing. With publishing disabled, builds still produce downloadable artifacts.

After changing enhancements, test, export Git-format patches relative to `patchBase`, and update series. Increment `revision` for an already published baseline. Never rewrite public tags. Patch conflicts or failed validation stop publication; incomplete releases resume from the original source tag.

Preserve the daily ledger at `data/personal-cultivation/<profile_id>.jsonl`. Investigate failures using `debug/asst.log`, `debug/gui.log` and Actions logs.
