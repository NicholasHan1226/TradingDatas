import { MagnifyingGlass, X } from "@phosphor-icons/react";

// Keep the input's accessible name stable when the clear action appears.
export function GlobalSearchField({ id, inputRef, label, value, clearLabel, shortcut, expanded, resultsId, activeResultId, onFocus, onChange, onKeyDown, onClear }) {
  return <div className="global-search-field">
    <MagnifyingGlass aria-hidden="true" />
    <label className="sr-only" htmlFor={id}>{label}</label>
    <input id={id} ref={inputRef} type="search" role="combobox" aria-autocomplete="list" aria-expanded={expanded} aria-controls={resultsId} aria-activedescendant={activeResultId} value={value} placeholder={label} onFocus={onFocus} onChange={onChange} onKeyDown={onKeyDown} />
    {value ? <button type="button" onClick={onClear} aria-label={clearLabel}><X /></button> : <kbd aria-hidden="true">{shortcut}</kbd>}
  </div>;
}
