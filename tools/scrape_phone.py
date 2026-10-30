"""Scroll a WhatsApp channel on an Android phone over adb and save every post to JSON.

Setup: enable Developer options + USB debugging, connect via USB, accept the prompt,
then open the channel in WhatsApp and leave it on screen at the newest post.

  python tools/scrape_phone.py --inspect                 # dump the current screen's UI nodes
  python tools/scrape_phone.py --channel "Jobs A" --out data/jobs_a.json

The resource ids below are WhatsApp's internal ids and change between versions.
Run --inspect first and adjust POST_IDS if nothing is found.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta

POST_IDS = {"com.whatsapp:id/message_text", "com.whatsapp:id/caption"}
# Day separators are recognised by their text (Today / Yesterday / weekday / full date), whatever their id:
# "com.whatsapp:id/date" is the time of day on each post ("13:06"), not a separator.
SETTLE_SECONDS = 0.5
SWIPE_MS = 800  # a slower drag leaves less fling, so the list stops where we expect
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
URL_RE = re.compile(r"https?://\S+")
DATE_FORMATS = ["%d %B %Y", "%B %d, %Y", "%d/%m/%Y", "%m/%d/%Y", "%d %b %Y", "%b %d, %Y", "%Y-%m-%d"]


def adb(*args, check=True):
    return subprocess.run(["adb", *args], capture_output=True, text=True, check=check).stdout


def dump_ui():
    adb("shell", "uiautomator", "dump", "/sdcard/ui.xml")
    return ET.fromstring(adb("exec-out", "cat", "/sdcard/ui.xml"))


def top_y(node):
    m = re.match(r"\[-?\d+,(-?\d+)\]", node.get("bounds", ""))  # negative when partly scrolled off the top
    return int(m.group(1)) if m else 0


def left_right(node):
    m = re.match(r"\[(-?\d+),-?\d+\]\[(-?\d+),", node.get("bounds", ""))
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def bottom_y(node):
    m = re.match(r"\[-?\d+,-?\d+\]\[-?\d+,(-?\d+)\]", node.get("bounds", ""))
    return int(m.group(1)) if m else 0


def parse_date(label):
    label = label.strip()
    low = label.lower()
    if low == "today":
        return date.today().isoformat()
    if low == "yesterday":
        return (date.today() - timedelta(days=1)).isoformat()
    if low in WEEKDAYS:  # WhatsApp shows the weekday name for the past week
        back = (date.today().weekday() - WEEKDAYS.index(low)) % 7 or 7
        return (date.today() - timedelta(days=back)).isoformat()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(label, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def screen_nodes(root):
    """Post and day-separator nodes on screen, top to bottom: dicts with kind, text, top, bottom."""
    found = []
    for n in root.iter("node"):
        text = (n.get("text") or "").strip()
        if not text:
            continue
        if n.get("resource-id") in POST_IDS:
            kind = "post"
        elif len(text) <= 20 and parse_date(text):
            kind = "date"
        else:
            continue
        left, right = left_right(n)
        found.append({"kind": kind, "text": text, "top": top_y(n), "bottom": bottom_y(n), "left": left, "right": right})
    return sorted(found, key=lambda x: x["top"])


def screen_items(root):
    """(post_text, date_or_None) for every post on screen, top to bottom."""
    out, current = [], None
    for n in screen_nodes(root):
        if n["kind"] == "date":
            current = parse_date(n["text"]) or current
        else:
            out.append((n["text"], current))
    return out


# Long posts are cut off with "... Read more". The label depends on the phone language; add yours here.
READ_MORE_LABELS = ["read more", "daha çox oxu", "daha çox", "devamını oku", "читать далее", "ещё", "leer más", "اقرأ المزيد"]
_TRUNC_RE = re.compile(r"(?:…|\.\.\.)\s*(?:%s)\s*$" % "|".join(re.escape(x) for x in READ_MORE_LABELS), re.I)
LABEL_ROW_OFFSET = 30  # px above the bottom of a post's text, where its last line (with the label) sits


def is_truncated(text):
    return bool(_TRUNC_RE.search(text))


def strip_label(text):
    return _TRUNC_RE.sub("", text).rstrip()


def tap(x, y):
    adb("shell", "input", "tap", str(int(x)), str(int(y)))


def whatsapp_in_front():
    """False if a tap sent us elsewhere (e.g. a link opened the browser). Unknown counts as True."""
    out = adb("shell", "dumpsys", "window", check=False)
    m = re.search(r"mCurrentFocus=\S+ \S+ ([\w.]+)/", out) or re.search(r"mCurrentFocus=.*? ([\w.]+)/", out)
    return True if not m else m.group(1) == "com.whatsapp"


HEADER_ID = "com.whatsapp:id/conversation_contact_name"  # the channel name at the top of the chat screen


def in_channel(root):
    return any(n.get("resource-id") == HEADER_ID for n in root.iter("node"))


def back_to_channel(root=None, tries=4):
    """Press BACK until the channel screen is showing again (e.g. after a tap opened a profile,
    group info or another chat). Returns the fresh screen dump, or None if we never got back."""
    root = root if root is not None else dump_ui()
    for _ in range(tries):
        if in_channel(root):
            return root
        adb("shell", "input", "keyevent", "4")
        time.sleep(0.8)
        root = dump_ui()
    return root if in_channel(root) else None


def expand_post(node):
    """Tap the 'Read more' at the end of a cut-off post. Returns the full text, or None.
    The label's x position depends on how long the last line is, so try a few spots along it."""
    prefix = strip_label(node["text"])[:80]
    width = node["right"] - node["left"]
    for fraction in (0.88, 0.72, 0.56, 0.4, 0.25):
        tap(node["left"] + fraction * width, node["bottom"] - LABEL_ROW_OFFSET)
        time.sleep(0.8)
        if not whatsapp_in_front():
            adb("shell", "input", "keyevent", "4")  # BACK from whatever the tap opened
            time.sleep(0.8)
            continue
        root = dump_ui()
        if not in_channel(root):  # the tap opened another WhatsApp screen (an icon, a profile, group info...)
            root = back_to_channel(root)
            if root is None:
                raise RuntimeError("a tap left the channel and BACK did not return to it; open the channel and re-run to resume")
            continue
        best = ""
        for n in root.iter("node"):
            t = (n.get("text") or "").strip()
            if t.startswith(prefix) and len(t) > len(best):
                best = t
        if best and not is_truncated(best) and len(best) > len(strip_label(node["text"])):
            in_list = any(n.get("resource-id") in POST_IDS and (n.get("text") or "").strip() == best for n in root.iter("node"))
            if not in_list:  # opened a separate full-text screen: go back to the channel
                adb("shell", "input", "keyevent", "4")
                time.sleep(0.8)
            return best
    return None


def swipe_px(width, y_from, y_to, ms):
    x = width // 2
    adb("shell", "input", "swipe", str(x), str(int(y_from)), str(x), str(int(y_to)), str(ms))


def pick_anchor(nodes):
    """Topmost node that starts on screen; used only to notice if a scroll lost all overlap."""
    return next((n for n in nodes if n["top"] >= 0), None)


def drag(width, height, pixels):
    """Slow drag (no fling that overshoots), then wait for the list to settle."""
    y0 = int(0.3 * height)
    swipe_px(width, y0, y0 + pixels, SWIPE_MS)
    time.sleep(SETTLE_SECONDS)


def signature(root):
    return hash(tuple((n.get("text"), n.get("bounds")) for n in root.iter("node") if n.get("text")))


def inspect():
    for n in dump_ui().iter("node"):
        if n.get("text"):
            print(f"{n.get('resource-id') or '-':55} y={top_y(n):5} {n.get('text')[:70]!r}")


def save_posts(path, posts):
    ordered = sorted(posts.values(), key=lambda p: p["date"] or "")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(ordered, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)  # atomic: never leaves a half-written file, even on Ctrl+C
    return ordered


def scrape(channel, out, max_stuck, fresh=False, step_fraction=0.4, until=None):
    size = re.search(r"(\d+)x(\d+)", adb("shell", "wm", "size"))
    width, height = int(size.group(1)), int(size.group(2))
    pixels = int(step_fraction * height)  # small fixed step: consecutive screens overlap a lot
    posts = {}  # (date, text) -> post; this is the duplicate check
    if not fresh and os.path.exists(out) and os.path.getsize(out):
        try:
            for p in json.load(open(out, encoding="utf-8")):
                posts[(p["date"], p["text"])] = p
            print(f"resuming with {len(posts)} saved posts (scraping again from the newest; use --fresh to ignore)")
        except (ValueError, KeyError, TypeError):
            os.replace(out, out + ".bak")  # unreadable file: keep it aside instead of overwriting it
            print(f"{out} could not be read; moved to {out}.bak and starting empty")
    prev_sig, stuck, lost, step, dupes = None, 0, 0, 0, 0
    anchor = None
    full_text, failed = {}, set()  # cut-off prefix -> full text; prefixes we could not expand
    deferred = {}  # cut-off posts seen but never opened: prefix -> (shortened text, date)
    def record(nodes):
        """Store the posts on this screen (deduplicated) and settle the dates of posts still undated."""
        nonlocal dupes
        current, on_screen = None, set()
        for n in nodes:
            if n["kind"] == "date":
                current = parse_date(n["text"]) or current
                continue
            text, d = n["text"], current
            if is_truncated(text):
                prefix = strip_label(text)[:80]
                if prefix in full_text:
                    text = full_text[prefix]
                elif prefix in failed:
                    text = strip_label(text) + " [cut off]"
                else:
                    deferred.setdefault(prefix, (strip_label(text) + " [cut off]", d))
                    continue  # not expanded yet: it is recorded once its full text is known
            on_screen.add(text)
            if d and (None, text) in posts:  # earlier sighting had no date yet
                posts[(d, text)] = posts.pop((None, text))
                posts[(d, text)]["date"] = d
            if (d, text) in posts or (d is None and any(k[1] == text for k in posts)):
                dupes += 1  # already stored (an undated sighting is the same post, just without its separator)
                continue
            posts[(d, text)] = {"channel": channel, "date": d, "text": text}
        # Posts still without a date that are off screen (newer, below it): their day separator is
        # above them, and the lowest separator now visible is the nearest one, so it is theirs.
        seps = [parse_date(n["text"]) for n in nodes if n["kind"] == "date"]
        if seps and seps[-1]:
            for key in [k for k in posts if k[0] is None and k[1] not in on_screen]:
                if (seps[-1], key[1]) not in posts:
                    posts[(seps[-1], key[1])] = posts.pop(key)
                    posts[(seps[-1], key[1])]["date"] = seps[-1]

    try:
        while stuck < max_stuck:
            root = dump_ui()
            if not in_channel(root):
                root = back_to_channel(root)
                if root is None:
                    raise RuntimeError("not on the channel screen and BACK did not return to it; open the channel and re-run to resume")
                print("\nleft the channel screen, went back")
                anchor = None
            nodes = screen_nodes(root)
            # Never go back: if nothing from the last screen is visible any more, just report it.
            if anchor and nodes and not any(n["text"] == anchor["text"] for n in nodes):
                lost += 1
                print(f"\nno overlap with the previous screen at step {step} (try a smaller --step)")
            # Record what is visible BEFORE tapping anything: opening a post changes the layout and can push
            # the posts around it off screen, and we only ever scroll towards older posts.
            record(nodes)
            # Then expand cut-off posts whose "Read more" is fully on screen. Lowest first: whatever an
            # expansion pushes down is already recorded or already expanded; what it pushes up is older
            # and comes back into view as we scroll.
            for _ in range(8):
                todo = max(
                    (
                        n for n in nodes
                        if n["kind"] == "post" and is_truncated(n["text"])
                        and strip_label(n["text"])[:80] not in full_text
                        and strip_label(n["text"])[:80] not in failed
                        and 0.08 * height < n["bottom"] <= height
                    ),
                    key=lambda n: n["bottom"],
                    default=None,
                )
                if not todo:
                    break
                prefix = strip_label(todo["text"])[:80]
                full = expand_post(todo)
                if full:
                    full_text[prefix] = full
                else:
                    failed.add(prefix)
                    print(f"\ncould not expand a cut-off post ({prefix[:40]!r}...), keeping the shortened text")
                back = back_to_channel()
                root = back if back is not None else root  # an XML element with no children is falsy, so no `or`
                nodes = screen_nodes(root)
                anchor = None  # the layout shifted, so skip the overlap check this step
                record(nodes)
            # --until: stop once a day separator older than the cutoff has been reached.
            if until and any((d := parse_date(n["text"])) and d < until for n in nodes if n["kind"] == "date"):
                print(f"\nreached {until}, stopping")
                break
            # Done only when the screen stops changing (top reached), not when no new posts appear.
            sig = signature(root)
            stuck = stuck + 1 if sig == prev_sig else 0
            prev_sig = sig
            if stuck:  # nothing moved: either the top, or WhatsApp is still loading older posts. Wait longer each time.
                print(f"\nscreen unchanged ({stuck}/{max_stuck}), waiting for older posts to load...")
                time.sleep(2.0 * stuck)
            links = len({u for p in posts.values() for u in URL_RE.findall(p["text"])})
            oldest = min((p["date"] for p in posts.values() if p["date"]), default="?")
            print(f"\r{len(posts)} posts, {links} links, back to {oldest}, {dupes} repeats skipped, {len(full_text)} expanded   ", end="", flush=True)
            if step % 10 == 0:
                save_posts(out, posts)
            anchor = pick_anchor(nodes)
            drag(width, height, pixels)
            step += 1
    except KeyboardInterrupt:
        print("\ninterrupted, saving what was collected")
    else:
        if stuck >= max_stuck:
            print(f"\nstopped: the screen did not change for {max_stuck} scrolls in a row. If this is not the top of the channel,"
                  " run the same command again WITHOUT --fresh while the phone is still at this spot; it continues from here.")
    finally:
        # Never drop a post silently: any cut-off post that was never opened is kept in its shortened form.
        left_cut = 0
        for prefix, (text, d) in deferred.items():
            if prefix not in full_text and prefix not in failed and not any(k[1] == text for k in posts):
                posts[(d, text)] = {"channel": channel, "date": d, "text": text}
                left_cut += 1
        if until:
            posts = {k: v for k, v in posts.items() if not v["date"] or v["date"] >= until}
        ordered = save_posts(out, posts)
    undated = sum(1 for p in ordered if not p["date"])
    print(f"\nsaved {len(ordered)} posts to {out} ({undated} without a date, {lost} lost-overlap warnings, {len(full_text)} expanded, {len(failed) + left_cut} left cut off, {step} steps)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--inspect", action="store_true")
    ap.add_argument("--channel")
    ap.add_argument("--out")
    ap.add_argument("--step", type=float, default=0.4, help="scroll distance as a fraction of the screen height (default 0.4)")
    ap.add_argument("--swipe-ms", type=int, default=SWIPE_MS, help="how long each drag takes (default 800; lower = faster but the list may coast past posts)")
    ap.add_argument("--settle", type=float, default=SETTLE_SECONDS, help="seconds to wait after each scroll before reading the screen (default 0.5)")
    ap.add_argument("--until", help="stop when posts older than this day are reached, e.g. 2025-12-01 (default: scroll to the very top)")
    ap.add_argument("--fresh", action="store_true", help="ignore an existing --out file instead of resuming")
    ap.add_argument("--max-stuck", type=int, default=6, help="stop after this many scrolls where the screen didn't change")
    a = ap.parse_args()
    SWIPE_MS, SETTLE_SECONDS = a.swipe_ms, a.settle
    if a.inspect:
        inspect()
    elif a.channel and a.out:
        scrape(a.channel, a.out, a.max_stuck, a.fresh, a.step, a.until)
    else:
        sys.exit("give --inspect, or both --channel and --out")
