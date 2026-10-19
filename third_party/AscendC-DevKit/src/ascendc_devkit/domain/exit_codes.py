"""L4 Domain — Exit codes (sysexits.h compatible)."""

EX_OK = 0
EX_GENERAL = 1
EX_USAGE = 64             # parameter error
EX_DATAERR = 65           # input data error
EX_CONFIG = 78            # environment/config error
EX_TEMPFAIL = 75          # transient error
EX_DECISION_PENDING = 73  # non-interactive decision pending, user must respond
EX_SIGINT = 130           # graceful stop (Ctrl+C)
EX_SIGKILL = 137          # forced exit
EX_TIMEOUT = 124          # workflow/stage timeout
