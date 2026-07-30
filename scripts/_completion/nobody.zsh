#compdef nobody nobody-backup nobody-calendar nobody-contacts nobody-cookbook nobody-docs nobody-gallery nobody-mail nobody-mcp nobody-memory nobody-notes nobody-personal nobody-preset nobody-research nobody-sessions nobody-signature nobody-skills nobody-tasks nobody-theme nobody-webhook
# Zsh tab-completion for the nobody umbrella + sub-CLIs.
#
# Drop in any directory on $fpath, e.g.:
#     fpath=(/path/to/nobody-ui/scripts/_completion $fpath)
#     autoload -U compinit; compinit
#
# Then `nobody <tab>` completes subcommands; `nobody mail <tab>`
# completes mail subcommands; `nobody-mail <tab>` works the same.

_nobody_scripts_dir() {
    local self="${(%):-%x}"
    while [[ -L "$self" ]]; do self="$(readlink "$self")"; done
    cd "${self:h}/.." && pwd
}

typeset -gA _nobody_subs

_nobody_refresh() {
    _nobody_subs=()
    local dir="$(_nobody_scripts_dir)"
    local py="$dir/../venv/bin/python"
    [[ -x "$py" ]] || py="$(command -v python3)"
    local f sub help_out commands
    for f in "$dir"/nobody-*; do
        [[ -x "$f" ]] || continue
        case "$f" in
            *.bak|*.pyc|*.pre-*) continue ;;
        esac
        sub="${${f:t}#nobody-}"
        help_out=$("$py" "$f" --help 2>/dev/null) || continue
        commands=$(echo "$help_out" | grep -oE '\{[a-z0-9_,-]+\}' | head -1 \
            | tr -d '{}' | tr ',' ' ')
        _nobody_subs[$sub]="$commands"
    done
}

_nobody() {
    [[ ${#_nobody_subs} -eq 0 ]] && _nobody_refresh

    local cmd="${words[1]}"

    if [[ "$cmd" == "nobody" ]]; then
        if (( CURRENT == 2 )); then
            local -a subs=(${(k)_nobody_subs} help)
            _describe 'subcommand' subs
            return
        fi
        local sub="${words[2]}"
        if [[ "$sub" == "help" ]] && (( CURRENT == 3 )); then
            local -a subs=(${(k)_nobody_subs})
            _describe 'subcommand' subs
            return
        fi
        if (( CURRENT == 3 )); then
            local -a sc=(${(s/ /)_nobody_subs[$sub]})
            _describe 'command' sc
            return
        fi
        return
    fi

    # nobody-foo <tab>
    local sub="${cmd#nobody-}"
    if (( CURRENT == 2 )); then
        local -a sc=(${(s/ /)_nobody_subs[$sub]})
        _describe 'command' sc
        return
    fi
}

_nobody "$@"
