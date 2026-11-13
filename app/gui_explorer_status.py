"""``TachoExplorer`` — integrity verdict, warning banner and the status bar.

Methods moved unchanged out of ``app/gui.py``; ``TachoExplorer`` inherits them
from :class:`StatusMixin`. Names the test-suite replaces on ``app.gui`` are read
through ``_live`` (see ``app.gui_base._LiveGuiNames``).
"""
from app.gui_base import (  # noqa: F401
    ACTIVE_BG,
    CAUTION,
    DANGER,
    DASHBOARD_TOOLTIP_BG,
    FONT_SMALL,
    GEN_COLORS,
    MUTED,
    SURFACE,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    VERDICT_CORRUPT,
    VERDICT_PARTIAL,
    VERDICT_VERIFIED,
    WARNING,
    _,
    _BADGE_WORDS,
    _WARN_POLL_MS,
    __version__,
    _bring_to_front,
    _elide_to_width,
    _envelope_notice,
    _header_notice,
    _icon,
    _integrity_bullets,
    _live,
    _pack_padx,
    _px,
    _right_padding,
    integrity_verdict,
    load_trace,
    os,
    tk,
    tkfont,
)


class StatusMixin:
    """Integrity verdict, warning banner and the status bar."""

    def _check_integrity(self, data, path):
            """Warn the user when a file shows signs of corruption or data loss."""
            meta = data.get("metadata", {})
            warnings = []

            trep = meta.get("trep_report") or {}
            if trep and trep.get("is_partial"):
                warnings.append(
                    f"\u2022 Download completeness: "
                    f"{trep.get('mandatory_ok', 0)}/{trep.get('mandatory_total', 0)} "
                    f"mandatory section(s) read ({trep.get('completeness_pct', 0)}%)")
                missing = trep.get("mandatory_missing") or []
                if missing:
                    warnings.append(
                        "\u2022 Missing mandatory section(s): "
                        + ", ".join(t["name"] for t in missing))
                suspect = trep.get("decoded_suspect") or []
                if suspect:
                    warnings.append(
                        "\u2022 Corrupted/implausible section(s) (data discarded): "
                        + ", ".join(t["name"] for t in suspect))
                if not trep.get("complete_walk", True):
                    # Single source: the bullet text (including the schema-violation
                    # explanation) comes from _integrity_bullets, which the tests
                    # call too. A walk that consumed every byte but found a section
                    # whose array list differs from Appendix 7 must say THAT.
                    shared, _notices = _integrity_bullets(data)
                    structure = [b for b in shared
                                 if "schema violation" in b
                                 or "did not reach the end of file" in b]
                    if structure:
                        warnings.extend(b for b in structure if b not in warnings)
                    else:
                        warnings.append(
                            "\u2022 The structural walk did not reach the end of file")

            salvaged = meta.get("salvage_recovered")
            if salvaged:
                warnings.append(
                    "\u2022 Data recovered from damaged regions (low confidence): "
                    + ", ".join(salvaged))

            for pw in meta.get("parse_warnings") or []:
                if isinstance(pw, dict):
                    warnings.append(
                        f"\u2022 Parsing phase '{pw.get('phase', '?')}' failed: "
                        f"{pw.get('message', 'unknown error')} "
                        f"(partial data shown)")

            heuristic = meta.get("heuristic_fields") or {}
            if heuristic:
                sections = ", ".join(sorted(heuristic.keys()))
                warnings.append(
                    f"\u2022 Some values were recovered heuristically (low "
                    f"confidence), not by deterministic spec parsing: {sections}")

            cov_report = data.get("coverage") or {}

            # Cryptographic validation: how much of the decoded data is signature-
            # verified vs. not (more meaningful than raw byte coverage).
            sv = data.get("signature_verification") or {}
            treps = sv.get("treps") or []
            if treps:
                # Reuse the verifier's own accounting (app/engine.py for G1,
                # core/crypto/vu_signature.py for G2). TREP 0x11/0x14 sensor
                # sections carry signature_valid=None ("signature not applicable")
                # and must not be recounted over len(treps): doing so produced a
                # spurious warning on a fully verified G1 VU download.
                if not sv.get("all_treps_valid"):
                    warnings.append(
                        f"\u2022 VU sections validated: "
                        f"{sv.get('summary') or 'not all sections were validated'}")
            elif sv.get("available") is False:
                warnings.append(
                    "\u2022 VU sections validated: 0 \u2014 signatures could not be "
                    "verified (VU public key unavailable)")

            efv = data.get("ef_signature_verification") or {}
            ef_results = efv.get("ef_results") or []
            if ef_results:
                ef_ok = sum(1 for e in ef_results if e.get("status") == "verified")
                ef_total = len(ef_results)
                if ef_ok < ef_total:
                    warnings.append(
                        f"\u2022 Card data validated: {ef_ok}/{ef_total} EF "
                        f"signature(s) verified; {ef_total - ef_ok} NOT validated")

            unknown = cov_report.get("classifications", {}).get("Unknown", 0)
            if unknown > 0:
                warnings.append(
                    f"\u2022 {unknown:,} bytes classified as Unknown (unparseable)")

            uncovered = cov_report.get("uncovered_ranges") or []
            if uncovered:
                warnings.append(
                    f"\u2022 {len(uncovered)} uncovered byte range(s) in the file")

            decoder_failures = meta.get("decoder_failure_count", 0)
            if decoder_failures > 0:
                warnings.append(
                    f"\u2022 {decoder_failures} decoder(s) failed during parsing")

            integrity = meta.get("integrity_check", "")
            if "Error" in integrity:
                warnings.append(f"\u2022 Integrity check: {integrity}")
            elif "Incomplete" in integrity:
                warnings.append(f"\u2022 Certificate chain: {integrity}")

            efv = data.get("ef_signature_verification") or {}
            ef_failed = efv.get("failed", 0)
            if ef_failed:
                warnings.append(f"\u2022 EF data signatures: {ef_failed} failed verification")
            ef_skipped = efv.get("skipped", 0)
            if ef_skipped:
                warnings.append(
                    f"\u2022 Card data signatures: {ef_skipped} EF signature(s) not checked")
            if (meta.get("is_vu") is not True and integrity_verdict(data) != VERDICT_VERIFIED
                    and not ef_failed and not ef_skipped):
                warnings.append(f"\u2022 Card integrity: {self._integrity_label(data)}")

            sv = data.get("signature_verification") or {}
            if sv.get("available") and not sv.get("msca_to_vu"):
                warnings.append("\u2022 VU signature: MSCA\u2192VU chain NOT verified")
            if sv.get("available") and not sv.get("root_anchored"):
                warnings.append("\u2022 VU signature: root ERCA key absent (not anchored)")
            trep_failed = sum(1 for t in (sv.get("treps") or []) if t.get("signature_valid") is False)
            if trep_failed:
                warnings.append(f"\u2022 VU signatures: {trep_failed} TREP section(s) failed")

            # A card image relayed through the vehicle unit gets ONE informational
            # bullet: it is the standard card plus the transfer header, not damage.
            # It is kept apart from the real warnings so a healthy file is never
            # announced as a warning.
            notice = _envelope_notice(data)
            notices = [note for note in (notice, _header_notice(data)) if note]
            bullets = warnings + notices

            self._integrity_warnings = bullets
            self._integrity_notices = notices
            self._integrity_file = os.path.basename(path)
            if warnings:
                self.integrity_banner.config(
                    text=_("{count} integrity warning(s) \u2014 click for details").format(
                        count=len(warnings)),
                    foreground=WARNING, takefocus=True, background=SURFACE,
                    image=_icon("status-warning", 16, self.integrity_banner) or "")
                header = _("The file may be incomplete or corrupted.\n\n{filename}\n\n").format(
                    filename=os.path.basename(path))
                self._warn_when_idle(_("File Integrity Warning"),
                                     header + "\n".join(bullets))
            elif notices:
                # Nothing is wrong with the file: it is a card image relayed
                # through the vehicle unit, which other tools report as corrupt.
                # Neutral wording and a neutral icon already used elsewhere (the
                # File Info document mark) — never the warning triangle.
                self.integrity_banner.config(
                    text=_("{count} note(s) \u2014 click for details").format(
                        count=len(notices)),
                    foreground=MUTED, takefocus=True, background=SURFACE,
                    image=_icon("file-info", 16, self.integrity_banner) or "")
                header = _("Note about this file.\n\n{filename}\n\n").format(
                    filename=os.path.basename(path))
                self._warn_when_idle(_("File Note"), header + "\n".join(bullets),
                                     kind="showinfo")
            else:
                # Valid file: no green tick, no banner — the absence of a warning
                # is the "all good" signal. The image is cleared with the text: a
                # label keeps the image it was configured with, and a lone warning
                # triangle over an empty label is a warning about nothing. An empty
                # banner also leaves the tab chain, and loses the focus tint a
                # previous file's warnings may have left on it.
                self._release_banner_focus()
                self.integrity_banner.config(text="", image="", takefocus=False,
                                             background=SURFACE)

    def _warn_when_idle(self, title, message, kind="showwarning"):
        """Show a warning box, but never while a file is still being opened.

        The box is modal. Opened from inside the render, it froze the window in
        its busy state — progress bar running, Open and Export disabled, the pane
        still on its "Loading…" placeholder — until the box was closed; when it
        opened behind the window (after a drag & drop from another application)
        the program looked stuck loading for good. Deferred to the idle loop it
        appears over a finished window, with the file already on screen.

        The wait is a *timer*, and that is the difference between a box on the
        owner's macOS build and no box at all. An idle callback is not a quiet
        place to park: ``update_idletasks()`` — the pump of the macOS render —
        runs the whole idle queue, re-armed callbacks included, so an idle
        ``_warn_when_idle`` fires *during* the render, sees the flags still set,
        and re-arms itself inside the same drain; each of those re-entries can
        also be swallowed by a Tk that is mid-redraw, and a queue that is busy
        for the whole render is a queue the notice can be lost in. A 50 ms timer
        cannot run inside an idle drain and leaves the box where it belongs:
        after the render has finished, with nothing left to re-enter.

        Before the box opens the window is flushed and raised
        (:func:`_bring_to_front`), because a modal box parented to a window that
        is still unmapped, behind the browser or not yet laid out can open where
        nobody sees it — and the notice is worth nothing if it is not on screen.
        """
        if self._parsing or self._rendering:
            if not self._destroyed:
                self.after(_WARN_POLL_MS, self._warn_when_idle, title, message, kind)
            return
        _bring_to_front(self)
        with load_trace.dialog(kind, title):
            getattr(_live.messagebox, kind)(title, message)

    def _activate_integrity_banner(self):
        """Return/space on the banner: the same dialog a click opens."""
        if self.integrity_banner.cget("text"):
            self._show_integrity_details()
        return "break"

    def _release_banner_focus(self):
        """Keyboard focus must not stay on a banner that has just been emptied."""
        try:
            if self.focus_get() is self.integrity_banner:
                self.tree.focus_set()
        except Exception:             # popdown Tk cannot name, or a half-built window
            pass

    def _on_banner_focus_in(self, _event=None):
        """Draw the banner's keyboard focus without losing its text's contrast.

        The status bar is a sunken frame, so a focus *ring* would move the
        label by a pixel; a filled background marks the focused control
        without touching the layout. The tint is the palette's own active-
        background colour, and it is dark enough to be seen, which is exactly
        why the warning orange (4.7:1 on the bar, 4.0:1 on the tint) gives way
        to the body foreground while the control has focus. The words and the
        warning icon do not change.
        """
        self.integrity_banner.configure(background=ACTIVE_BG,
                                       foreground=TEXT_PRIMARY)

    def _on_banner_focus_out(self, _event=None):
        self.integrity_banner.configure(background=SURFACE, foreground=WARNING)

    def _show_integrity_details(self):
        """Show the collected integrity warnings on demand (banner click).

        A file whose only bullet is the transfer-header note is not announced as a
        warning: it gets the neutral title, header and icon level.
        """
        bullets = getattr(self, "_integrity_warnings", None) or []
        notices = getattr(self, "_integrity_notices", None) or []
        if not bullets:
            _live.messagebox.showinfo(
                _("File Integrity"),
                _("{filename}\n\nNo integrity issues detected.").format(
                    filename=getattr(self, "_integrity_file", "")))
            return
        if not [bullet for bullet in bullets if bullet not in notices]:
            header = _("Note about this file.\n\n{filename}\n\n").format(
                filename=getattr(self, "_integrity_file", ""))
            _live.messagebox.showinfo(_("File Note"), header + "\n".join(bullets))
            return
        header = _("The file may be incomplete or corrupted.\n\n{filename}\n\n").format(
            filename=getattr(self, "_integrity_file", ""))
        _live.messagebox.showwarning(_("File Integrity Warning"),
                               header + "\n".join(bullets))

    def _update_top_bar(self, data):
        """Refresh filename, generation badge and status badge."""
        meta = data.get("metadata", {})
        gen = meta.get("generation", "Unknown")
        self.lbl_file.config(text=os.path.basename(self.current_file))
        self.lbl_gen.config(text=f"\u25cf {gen}",
                            foreground=GEN_COLORS.get(gen, GEN_COLORS["Unknown"]))
        self._update_status_badge(data)

    def _integrity_label(self, data):
        """Return a human-readable integrity summary for File Info and status bar.

        The label must reflect the actual trust verdict: a partial/unanchored
        chain or an unverified EF is never collapsed into a blanket "verified".
        """
        meta = data.get("metadata") or {}
        integrity = meta.get("integrity_check", "")
        efv = data.get("ef_signature_verification") or {}
        sv = data.get("signature_verification") or {}
        is_vu = meta.get("is_vu") is True

        if is_vu:
            sv_ok = sv.get("all_treps_valid") is True
            vu_chain_ok = sv.get("msca_to_vu") is True
            if sv_ok and vu_chain_ok and sv.get("root_anchored"):
                return _("VU signatures verified (root anchored)")
            if sv_ok and vu_chain_ok:
                return _("VU TREP signatures verified (chain partial)")
            if sv_ok:
                return _("VU TREP signatures valid (chain unverified)")
        else:
            if integrity_verdict(data) == VERDICT_VERIFIED:
                return _("All signatures verified")
            if efv.get("failed", 0):
                # "Signature mismatch", not "Card data signature mismatch": the
                # qualifier repeated the file's own type (a card) and pushed the
                # verdict to 205-374 px, wider than the summary panel's 187 px
                # value column in 32 of 34 catalogs (see
                # tests/unit/test_gui_summary_default.py).
                return _("Signature mismatch")
            if efv.get("skipped", 0):
                return _("EF signatures incomplete")
            # Chain-level failures must surface even when there is no signed EF
            # pair to explain them (never hidden behind "No EF signatures").
            if "Invalid" in integrity:
                return _("Certificate chain invalid")
            if "anchor" in integrity.lower() or "Missing ERCA" in integrity:
                return _("Certificate chain not anchored to a trusted root")
            if "not trusted" in integrity:
                return _("Card signing key not trusted")
            if "EF Signature Verification Failed" in integrity:
                return _("EF signature verification failed")
            if "Error" in integrity:
                return _("Verification error")
            if not (efv.get("ef_results") or []):
                return _("No EF signatures verified")
            if integrity.startswith("Partial"):
                return _("Partial verification")
            if "Incomplete" in integrity:
                return _("Incomplete certificates")
            return integrity or "N/A"

        # VU negative/corrupt fallbacks.
        if integrity.startswith("Partial"):
            return _("Partial verification")
        if integrity == "Invalid Certificate Chain":
            return _("Certificate chain invalid")
        if "Missing ERCA" in integrity:
            return _("ERCA root not available")
        if "Incomplete" in integrity:
            return _("Incomplete certificates")
        if "Error" in integrity:
            return _("Verification error")
        return integrity or "N/A"

    def _update_status_badge(self, data):
        """Compose the colour-coded integrity label. Only problems are shown;
        a fully valid file displays no badge (its absence is the OK signal)."""
        integrity = (data.get("metadata") or {}).get("integrity_check", "")
        efv = data.get("ef_signature_verification") or {}
        sv = data.get("signature_verification") or {}
        is_vu = (data.get("metadata") or {}).get("is_vu") is True
        verdict = integrity_verdict(data)

        label = self._integrity_label(data)
        # The badge is a status *icon* plus its words: the four status glyphs of
        # the commissioned set are told apart by shape (circle/check,
        # triangle/!, circle/cross, circle/?), so the meaning does not hang on
        # the colour alone.
        badge = None

        if is_vu:
            sv_ok = sv.get("all_treps_valid") is True
            vu_chain_ok = sv.get("msca_to_vu") is True
            if sv_ok and vu_chain_ok and sv.get("root_anchored"):
                text, color, badge = "", MUTED, None
            elif sv_ok:
                text, color, badge = label, WARNING, "status-warning"
            elif verdict == VERDICT_CORRUPT:
                text, color, badge = label, DANGER, "status-error"
            elif verdict == VERDICT_PARTIAL:
                text, color, badge = label, CAUTION, "status-warning"
            elif "Incomplete" in integrity:
                text, color, badge = _("Incomplete certificates"), MUTED, "status-unknown"
            elif "Error" in integrity:
                text, color, badge = _("Parse error"), DANGER, "status-error"
            else:
                # Reached only when the file is NOT fully trusted (the
                # all-good case is returned above): VERDICT_UNVERIFIED with
                # no "Incomplete"/"Error" marker, e.g. a VU whose chain is
                # anchored but whose TREP signatures failed
                # ("Partial (VU - chain ok)"). Hiding the badge here read as
                # a clean file; it must warn like every other non-verified
                # VU state (R1, Batch 1 refutation).
                text, color, badge = label, WARNING, "status-warning"
        elif verdict == VERDICT_VERIFIED:
            text, color, badge = "", MUTED, None
        elif verdict == VERDICT_CORRUPT or efv.get("failed", 0):
            text, color, badge = label, DANGER, "status-error"
        elif "Incomplete" in integrity:
            text, color, badge = _("Incomplete certificates"), MUTED, "status-unknown"
        elif "Error" in integrity:
            text, color, badge = _("Parse error"), DANGER, "status-error"
        else:
            text, color, badge = label, WARNING, "status-warning"

        # An empty image name clears a previous badge: a label keeps the image
        # it was configured with, and a clean file must not inherit the last
        # file's warning icon.
        self._set_status_text(text, _icon(badge, 16, self) if badge else None,
                              foreground=color)
        # Also update the window title with a compact status (problems only).
        # The window title is plain text: it has no icon slot, so it carries the
        # short word for the badge instead of a glyph.
        parts = [f"Tacho Explorer v{__version__}",
                 _BADGE_WORDS.get(badge or "", ""),
                 os.path.basename(self.current_file or "")]
        self.title("  ".join(p for p in parts if p))

    def _set_status_text(self, text, image, foreground=None):
        """Store the whole verdict (and its icon) and show as much as fits."""
        self._status_text = text or ""
        self._status_icon = image
        options = {"text": self._status_text, "image": image or "",
                   "compound": tk.LEFT}
        if foreground is not None:
            options["foreground"] = foreground
        self.lbl_status.config(**options)
        self._fit_status()

    def _status_label_font(self):
        """The font the verdict is drawn with, for measuring it."""
        if self._status_font is None:
            self._status_font = tkfont.Font(font=self.lbl_status.cget("font"))
        return self._status_font

    def _status_available_width(self):
        """How many pixels the verdict may use, with the right-hand block kept.

        Everything here is deliberately independent of the label's current
        text, because the answer decides that text: an elided label is narrower
        than the space it was given, so measuring *its* width would elide it
        again on the next pass, and each pass would find a different number
        (pack squeezes the generation badge out of the bar at one width and
        lets it back in at another — the two widths then oscillate forever).
        So the width is the window's, minus the fixed left block the label
        starts after, minus what the right-hand block *asks* for.
        """
        reserved = 0
        for neighbour in (self.lbl_gen, self.btn_lang, self.btn_help):
            if neighbour is None:        # no Help button on macOS (native menu)
                continue
            try:
                # What it asks for plus the padx it is packed with, on both
                # sides: the badge is packed with padx=8, which is 16 px.
                reserved += neighbour.winfo_reqwidth() + _pack_padx(neighbour)
            except tk.TclError:          # a window that is being torn down
                continue
        # The label's x is relative to the *bar* it is packed in, which is
        # inset by the frame's padding; the window's width is not. Mixing the
        # two overstated the budget by that padding.
        left = self.lbl_status.winfo_rootx() - self.winfo_rootx()
        bar = self.lbl_status.master
        available = (self.winfo_width() - left - reserved
                     - _right_padding(bar))
        # What the label adds around its text (the icon, its gap and the
        # widget's own padding) is read off the label itself: the difference
        # between what it asks for and what its current text measures does not
        # depend on which text that is.
        font = self._status_label_font()
        available -= (self.lbl_status.winfo_reqwidth()
                      - font.measure(self.lbl_status.cget("text")))
        return available

    def _fit_status(self):
        """Show the whole verdict, or as much of it as ends in an ellipsis.

        Runs on every resize of the label and whenever the verdict changes, so
        a longer translation, a narrower window or a new file is reflected
        immediately instead of staying clipped.
        """
        label = self.lbl_status
        if not self._status_text:
            # Nothing to reveal any more: a tip left on screen would describe a
            # file that is no longer loaded.
            self._hide_status_tip()
        if not self._status_text or not isinstance(label, tk.Widget):
            # No window to measure (a stub in a test): the plain text stands.
            return
        if label.winfo_width() <= 1:
            # Not laid out yet — the <Configure> that follows the first pack
            # fits it.
            return
        available = self._status_available_width()
        font = self._status_label_font()
        shown = self._status_text
        if available <= 0:
            # No room at all: keep a mark of the cut, so the label stays
            # something to hover (and reaches its tooltip) instead of blank.
            shown = "\u2026"
        elif font.measure(shown) > available:
            shown = _elide_to_width(shown, font, available)
        if label.cget("text") != shown:
            label.config(text=shown)
            self._hide_status_tip()

    def _show_status_tip(self, _event=None):
        """Reveal the whole verdict when the label had to shorten it."""
        if not self._status_text or self.lbl_status.cget("text") == self._status_text:
            self._hide_status_tip()
            return
        if self._status_tip is None:
            self._status_tip = tk.Label(self, text="", bg=DASHBOARD_TOOLTIP_BG,
                                        relief=tk.SOLID, borderwidth=1,
                                        font=FONT_SMALL, fg=TEXT_SECONDARY,
                                        padx=6, pady=2, justify=tk.LEFT)
        tip = self._status_tip
        tip.config(text=self._status_text, wraplength=_px(420))
        tip.update_idletasks()
        # Under the label, kept inside the window: a tooltip that runs off the
        # right edge would hide the very words it exists to show. Both edges
        # are measured from the window's own origin, because the label's
        # winfo_x/y are relative to the toolbar frame it is packed in.
        x = min(self.lbl_status.winfo_rootx() - self.winfo_rootx(),
                max(0, self.winfo_width() - tip.winfo_reqwidth() - _px(4)))
        y = (self.lbl_status.winfo_rooty() - self.winfo_rooty()
             + self.lbl_status.winfo_height())
        tip.place(x=x, y=y)
        tip.lift()

    def _hide_status_tip(self):
        """Hide the verdict reveal, if one is showing."""
        try:
            if self._status_tip is not None:
                self._status_tip.place_forget()
        except Exception:             # a half-built or torn-down window
            pass
