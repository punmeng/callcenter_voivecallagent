# Billing records (sample data for the UC3 billing agent)

Upload this file as **File search / knowledge** on the Foundry agent `voicecall-uc3-billing`,
then Publish. The billing agent will ground answers (current amount, due date, status) from it.
Replace with real data or a billing API/tool for production.

## Accounts

| Account | Member No. | Current bill (NT$) | Billing period | Due date | Status |
| --- | --- | --- | --- | --- | --- |
| AA123456 | M-1001 | 1,280 | 2026-06 | 2026-07-15 | Unpaid |
| BB987654 | M-1002 | 860 | 2026-06 | 2026-07-15 | Paid |
| CC246810 | M-1003 | 2,450 | 2026-06 | 2026-07-15 | Unpaid |
| DD135790 | M-1004 | 0 | 2026-06 | 2026-07-15 | Paid |

## Details

- Account AA123456 (member M-1001): current bill is NT$1,280 for the 2026-06 billing period,
  due 2026-07-15, status unpaid. Recent charges: monthly plan NT$999, extra data NT$281.
- Account BB987654 (member M-1002): current bill is NT$860 for 2026-06, due 2026-07-15, already paid.
- Account CC246810 (member M-1003): current bill is NT$2,450 for 2026-06, due 2026-07-15, unpaid.
  Recent charges: premium plan NT$1,999, international roaming NT$451.
- Account DD135790 (member M-1004): no outstanding balance for 2026-06 (NT$0), paid.

## Notes

- If an account number is not listed here, tell the caller you don't have that account's
  billing data and offer to have a human specialist follow up.
- Amounts are in New Taiwan Dollars (NT$).
