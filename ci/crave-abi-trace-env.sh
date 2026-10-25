# Loaded only by Bash during ABI preparation, after Android environment setup.
# Do not enable nounset/errexit here: the helper owns those settings.
set -E
trap 'trace_rc=$?; printf "ERR rc=%s pid=%s source=%s line=%s command=%q\n" "$trace_rc" "$BASHPID" "${BASH_SOURCE[*]}" "$LINENO" "$BASH_COMMAND" >&9' ERR
trap 'trace_rc=$?; printf "EXIT rc=%s pid=%s source=%s line=%s\n" "$trace_rc" "$BASHPID" "${BASH_SOURCE[*]}" "$LINENO" >&9' EXIT
