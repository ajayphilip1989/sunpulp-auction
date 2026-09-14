"""
SunPulp Reverse Auction — classroom app
Basics of Purchasing, KREA University

Three roles, selected in the sidebar:
  Bidder    — students. Enter team code, bid or predict.
  Projector — the screen at the front. Ladder only.
  Instructor— you. Open/close rounds, reveal everything.

State is held in one shared object and mirrored to state.json so a
restart does not lose the auction.
"""

import json
import os
import time
from datetime import datetime

import streamlit as st

# --------------------------------------------------------------------------
# CONFIGURATION — edit costs, codes and items here
# --------------------------------------------------------------------------

INSTRUCTOR_PASSWORD = "sunpulp2026"        # change before class
PROJECTOR_PASSWORD = "screen26"             # for the front screen only

# NEVER put the instructor view on the projector: it shows every team's cost
# and margin. Use the Projector view, which shows only what the class may see.
DECREMENT = 0.10                            # minimum decrement, same in all auctions
STATE_FILE = "state.json"

AUCTIONS = {
    1: {
        "name": "Auction 1",
        "item": "Corrugated cartons for FreshSip",
        "quantity": "500,000 cartons",
        "unit": "per carton",
        "ceiling": 11.50,
        "show_l1": False,      # rank-only auction
        "predictions": False,  # no prediction task in auction 1
        "teams": {
            "K7": 7.20, "M2": 7.80, "R9": 8.05, "T4": 8.15, "B6": 8.60,
            "J3": 9.30, "W8": 9.45, "D5": 9.80, "P1": 10.55,
        },
    },
    2: {
        "name": "Auction 2",
        "item": "Corrugated cartons for FreshSip",
        "quantity": "500,000 cartons",
        "unit": "per carton",
        "ceiling": 11.50,
        "show_l1": True,
        "predictions": True,
        "teams": {
            "H2": 7.20, "N5": 7.80, "C8": 8.05, "V3": 8.15, "L9": 8.60,
            "G4": 9.30, "Z7": 9.45, "F1": 9.80, "Q6": 10.55,
        },
    },
    3: {
        "name": "Auction 3",
        "item": "Printed shrink sleeves for FreshSip bottles",
        "quantity": "2,000,000 sleeves",
        "unit": "per 100 sleeves",
        "ceiling": 31.00,
        "show_l1": True,
        "predictions": True,
        "teams": {
            "X4": 25.20, "S8": 27.00, "A2": 27.25, "Y6": 27.35, "E9": 27.80,
            "U3": 28.50, "I7": 28.65, "O5": 29.00, "TT": 29.75, "MM": 30.05,
        },
    },
}



# One PIN per team, printed on that team's cost card. Stops a team bidding
# under another team's code. Change these freely; they only need to be unique
# enough that a neighbour cannot guess them.
PINS = {
    # Auction 1
    "K7": "4182", "M2": "7315", "R9": "2946", "T4": "6073", "B6": "5821",
    "J3": "3497", "W8": "1638", "D5": "9254", "P1": "8706",
    # Auction 2
    "H2": "5390", "N5": "2714", "C8": "6842", "V3": "1075", "L9": "9436",
    "G4": "3268", "Z7": "7519", "F1": "4087", "Q6": "8651",
    # Auction 3
    "X4": "2073", "S8": "6418", "A2": "9527", "Y6": "3841", "E9": "7192",
    "U3": "5604", "I7": "1385", "O5": "4769", "TT": "8230", "MM": "6947",
}


# --------------------------------------------------------------------------
# SHARED STATE
# --------------------------------------------------------------------------

def blank_state():
    return {
        "auction": 1,
        "round": 0,
        "open": False,
        "bids": [],          # {auction, round, code, bidding, bid, status, names, ts}
        "predictions": [],   # {auction, round, code, value, names, ts}
        "revealed": False,
    }


@st.cache_resource
def get_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return blank_state()


def save(state):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f)
    except Exception:
        pass


# --------------------------------------------------------------------------
# AUCTION LOGIC
# --------------------------------------------------------------------------

def visible_round(state):
    """While a round is open, everything shown and checked refers to the last
    CLOSED round. Bids placed in the open round stay hidden until it closes,
    so every team in a round bids against the same benchmark."""
    return state["round"] - 1 if state["open"] else state["round"]


def accepted_bids(state, auction, upto_round=None):
    """Latest accepted bid per team, up to and including a round."""
    out = {}
    for b in state["bids"]:
        if b["auction"] != auction:
            continue
        if upto_round is not None and b["round"] > upto_round:
            continue
        if b["status"] != "accepted" or not b["bidding"]:
            continue
        out[b["code"]] = b["bid"]
    return out


def bid_times(state, auction, upto_round=None):
    """When each team last moved to its standing price — used to break ties."""
    out = {}
    for b in state["bids"]:
        if b["auction"] != auction:
            continue
        if upto_round is not None and b["round"] > upto_round:
            continue
        if b["status"] != "accepted" or not b["bidding"]:
            continue
        out[b["code"]] = b["ts"]
    return out


def last_submission(state, auction, code):
    rows = [b for b in state["bids"] if b["auction"] == auction and b["code"] == code]
    return rows[-1] if rows else None


def standing_l1(state, auction, upto_round=None):
    if upto_round is None:
        upto_round = visible_round(state)
    bids = accepted_bids(state, auction, upto_round)
    return min(bids.values()) if bids else None


def withdrawn(state, auction, upto_round=None):
    """Teams whose most recent submission said they are no longer bidding."""
    if upto_round is None:
        upto_round = visible_round(state)
    out = set()
    for code in AUCTIONS[auction]["teams"]:
        rows = [b for b in state["bids"] if b["auction"] == auction
                and b["code"] == code and b["round"] <= upto_round]
        if rows and not rows[-1]["bidding"]:
            out.add(code)
    return out


def ladder(state, auction, upto_round=None):
    if upto_round is None:
        upto_round = visible_round(state)
    bids = accepted_bids(state, auction, upto_round)
    gone = withdrawn(state, auction, upto_round)
    times = bid_times(state, auction, upto_round)
    live = {c: p for c, p in bids.items() if c not in gone}
    # Equal bids are ranked by who submitted first.
    return sorted(live.items(), key=lambda kv: (kv[1], times.get(kv[0], ""), kv[0]))


def team_rank(state, auction, code):
    for i, (c, _) in enumerate(ladder(state, auction), start=1):
        if c == code:
            return i, len(ladder(state, auction))
    return None, len(ladder(state, auction))


def validate(state, auction, code, bid):
    """Returns (status, message)."""
    cfg = AUCTIONS[auction]
    if bid > cfg["ceiling"]:
        return "rejected", f"Above the ceiling price of Rs. {cfg['ceiling']:.2f}. Not accepted."

    # Round 1 is the opening round: any price at or below the ceiling is accepted.
    # The decrement rule applies only to improving on a standing lowest bid.
    if state["round"] <= 1:
        return "accepted", None

    vr = visible_round(state)
    prev_rows = [b for b in state["bids"]
                 if b["auction"] == auction and b["code"] == code
                 and b["round"] <= vr
                 and b["status"] == "accepted" and b["bidding"]]
    prev = prev_rows[-1]["bid"] if prev_rows else None

    if prev is not None and bid > prev:
        return "rejected", (f"You cannot raise your bid. Your standing bid is "
                            f"Rs. {prev:.2f}.")

    if prev is not None and abs(bid - prev) < 1e-9:
        return "pass", f"Recorded as a pass. Your bid stays at Rs. {prev:.2f}."

    l1 = standing_l1(state, auction)
    if l1 is not None and bid > l1 - DECREMENT + 1e-9:
        if prev is not None and bid < prev:
            return "rejected", (f"Rejected. A new bid must be at least Rs. {DECREMENT:.2f} "
                                f"below the standing lowest bid. Your previous bid stands.")
        return "rejected", (f"Rejected. A new bid must be at least Rs. {DECREMENT:.2f} "
                            f"below the standing lowest bid.")

    return "accepted", None


def team_names(state, auction, code):
    """The names this team entered on its first submission."""
    for b in state["bids"]:
        if b["auction"] == auction and b["code"] == code and b.get("names"):
            return b["names"]
    return ""


def bids_csv(state):
    rows = ["auction,round,team_code,names,cost,bid,status,timestamp"]
    for b in state["bids"]:
        cfg = AUCTIONS[b["auction"]]
        cost = cfg["teams"].get(b["code"], "")
        names = str(b.get("names", "")).replace('"', "'")
        bid = "" if b["bid"] is None else f"{b['bid']:.2f}"
        rows.append(f'{b["auction"]},{b["round"]},{b["code"]},"{names}",'
                    f'{cost},{bid},{b["status"]},{b["ts"]}')
    return "\n".join(rows)


def predictions_csv(state):
    rows = ["auction,round,team_code,names,predicted_l1,timestamp"]
    for p in state["predictions"]:
        names = str(p.get("names", "")).replace('"', "'")
        rows.append(f'{p["auction"]},{p["round"]},{p["code"]},"{names}",'
                    f'{p["value"]:.2f},{p["ts"]}')
    return "\n".join(rows)


def money(x, unit=""):
    return f"Rs. {x:,.2f}{(' ' + unit) if unit else ''}"


def already_predicted(state, auction, rnd, code):
    return any(p["auction"] == auction and p["round"] == rnd and p["code"] == code
               for p in state["predictions"])


def prediction_box(state, code, label):
    """Shown to anyone not actively bidding in the running auction."""
    auction = state["auction"]
    cfg = AUCTIONS[auction]
    rnd = state["round"]

    if not cfg["predictions"]:
        st.info("No prediction is asked for in this auction. Please watch.")
        return

    if not state["open"]:
        st.warning("Predictions are accepted only while a round is open.")
        return

    if already_predicted(state, auction, rnd, code):
        st.success("Your prediction for this round has been recorded.")
        return

    st.subheader(f"{cfg['name']} — round {rnd}")
    st.caption(label)
    pred = st.number_input(
        "Your prediction of the L1 price at the end of this round",
        min_value=0.0, max_value=float(cfg["ceiling"]),
        step=DECREMENT, format="%.2f", key=f"obs{code}{auction}{rnd}")
    if st.button("Submit prediction", type="primary"):
        state["predictions"].append({
            "auction": auction, "round": rnd, "code": code,
            "value": float(pred), "names": "",
            "ts": datetime.now().isoformat(timespec="seconds"),
        })
        save(state)
        st.success("Prediction recorded.")
        time.sleep(1)
        st.rerun()


# --------------------------------------------------------------------------
# BIDDER VIEW
# --------------------------------------------------------------------------

def bidder_view(state):
    st.title("SunPulp Foods — Reverse Auction")

    # A team stays signed in because the code and PIN are carried in the URL.
    # A browser refresh starts a new Streamlit session and would otherwise wipe
    # the sign-in, so the URL is what makes refreshing painless.
    qp = st.query_params
    signed = st.session_state.get("team_code")

    if not signed:
        qcode = (qp.get("code") or "").strip().upper()
        qpin = (qp.get("pin") or "").strip()
        if qcode in PINS and qpin == PINS[qcode]:
            st.session_state["team_code"] = qcode
            signed = qcode

    if not signed:
        code = st.text_input("Your team code").strip().upper()
        pin = st.text_input("PIN", max_chars=4).strip()
        if not code or not pin:
            st.info("Enter the team code and PIN printed on your cost card. "
                    "You will only be asked once.")
            return
        if code not in PINS:
            st.error("That code is not recognised. Check your cost card.")
            return
        if pin != PINS[code]:
            st.error("That PIN does not match the code. Check your cost card.")
            return
        st.session_state["team_code"] = code
        st.query_params["code"] = code
        st.query_params["pin"] = pin
        st.rerun()

    code = signed

    auction = None
    for a, cfg in AUCTIONS.items():
        if code in cfg["teams"]:
            auction = a
            break
    if auction is None:
        st.error("That code is not recognised. Check your cost card.")
        return

    if st.sidebar.button("Sign out"):
        st.session_state.pop("team_code", None)
        st.query_params.clear()
        st.rerun()

    cfg = AUCTIONS[auction]
    cost = cfg["teams"][code]

    st.caption(f"{cfg['name']} — {cfg['item']}")
    c1, c2, c3 = st.columns(3)
    c1.metric("Your cost", money(cost))
    c2.metric("Ceiling price", money(cfg["ceiling"]))
    c3.metric("Quantity", cfg["quantity"])
    st.caption(f"All prices are {cfg['unit']}. Minimum decrement Rs. {DECREMENT:.2f}.")

    if state["auction"] != auction:
        run = state["auction"]
        rcfg = AUCTIONS[run]
        st.divider()
        st.info(f"{cfg['name']} is not running. {rcfg['name']} is under way — "
                f"{rcfg['item']}.")
        if rcfg["show_l1"]:
            l1 = standing_l1(state, run)
            st.metric(f"{rcfg['name']} — current lowest bid (L1)",
                      money(l1) if l1 is not None else "—")
            st.caption(f"All prices {rcfg['unit']}. "
                       f"Ceiling {money(rcfg['ceiling'])}.")
        prediction_box(state, code,
                       "You are not bidding in this auction. Predict where it will stand.")
        return

    rnd = state["round"]
    vr = visible_round(state)
    rank, total = team_rank(state, auction, code)

    if vr >= 1:
        if rank:
            st.success(f"After round {vr}: your position is **L{rank}** of {total} live bidders.")
        else:
            st.info("You have no standing bid.")
        if cfg["show_l1"]:
            l1 = standing_l1(state, auction)
            if l1 is not None:
                st.metric("Current lowest bid (L1)", money(l1))
        else:
            st.caption("Bid amounts are not disclosed in this auction.")

    if code in withdrawn(state, auction):
        st.divider()
        st.info("You have withdrawn from the bidding.")
        prediction_box(state, code,
                       "You are out of the bidding. Predict where this auction will stand.")
        return

    if not state["open"]:
        st.warning("Bidding is closed. Wait for the next round to open.")
        return

    st.divider()
    st.subheader(f"Round {rnd}")

    already = [b for b in state["bids"]
               if b["auction"] == auction and b["code"] == code and b["round"] == rnd]
    if already:
        last = already[-1]
        if last["bidding"]:
            st.info(f"Submitted this round: {money(last['bid'])} — {last['status']}.")
        else:
            st.info("Submitted this round: withdrawn from bidding.")
        if not st.checkbox("Change my submission for this round"):
            return

    known = team_names(state, auction, code)
    if known:
        names = known
        st.caption(f"Bidding as: {known}")
    else:
        names = st.text_input("Team members' names (asked once only)",
                              key=f"nm{code}{rnd}")

    still = st.radio("Are you still bidding?", ["Yes", "No"], key=f"sb{code}{rnd}")

    if still == "Yes":
        bid = st.number_input(f"Your bid ({cfg['unit']})", min_value=0.0,
                              max_value=float(cfg["ceiling"]), step=DECREMENT,
                              format="%.2f", key=f"bd{code}{rnd}")
        st.caption("To pass this round, enter the same amount as your previous bid.")
        if st.button("Submit bid", type="primary"):
            if not names.strip():
                st.error("Please enter your names.")
                return
            status, msg = validate(state, auction, code, float(bid))
            state["bids"].append({
                "auction": auction, "round": rnd, "code": code, "bidding": True,
                "bid": float(bid), "status": status, "names": names.strip(),
                "ts": datetime.now().isoformat(timespec="seconds"),
            })
            save(state)
            if status == "accepted":
                st.success(f"Bid of {money(float(bid))} accepted.")
            elif status == "pass":
                st.info(msg)
            else:
                st.error(msg)
            time.sleep(1)
            st.rerun()
    else:
        st.caption("Withdraw once bidding below your cost would lose you money.")
        pred = None
        if cfg["predictions"]:
            pred = st.number_input("Your prediction of the L1 price at the end of the next round",
                                   min_value=0.0, max_value=float(cfg["ceiling"]),
                                   step=DECREMENT, format="%.2f", key=f"pr{code}{rnd}")
        if st.button("Confirm withdrawal", type="primary"):
            if not names.strip():
                st.error("Please enter your names.")
                return
            state["bids"].append({
                "auction": auction, "round": rnd, "code": code, "bidding": False,
                "bid": None, "status": "withdrawn", "names": names.strip(),
                "ts": datetime.now().isoformat(timespec="seconds"),
            })
            if pred is not None:
                state["predictions"].append({
                    "auction": auction, "round": rnd, "code": code,
                    "value": float(pred), "names": names.strip(),
                    "ts": datetime.now().isoformat(timespec="seconds"),
                })
            save(state)
            st.success("Recorded. You are out of the bidding.")
            time.sleep(1)
            st.rerun()


# --------------------------------------------------------------------------
# PROJECTOR VIEW
# --------------------------------------------------------------------------

def projector_view(state):
    auction = state["auction"]
    cfg = AUCTIONS[auction]
    vr = visible_round(state)
    st.title(f"{cfg['name']} — Round {state['round']}")
    st.caption(f"{cfg['item']} · {cfg['quantity']} · all prices {cfg['unit']}")
    st.caption(f"Standings after round {vr}." if vr >= 1
               else "No results yet.")

    if cfg["show_l1"]:
        l1 = standing_l1(state, auction)
        st.metric("Current lowest bid (L1)", money(l1) if l1 is not None else "—")
    else:
        st.caption("Bid amounts are not disclosed in this auction.")

    rows = ladder(state, auction)
    if not rows:
        st.info("No bids yet.")
    else:
        table = [{"Position": f"L{i}", "Team": c} for i, (c, _) in enumerate(rows, start=1)]
        if cfg["show_l1"]:
            for r, (_, p) in zip(table, rows):
                r["Bid"] = money(p)
        st.dataframe(table, hide_index=True, width="stretch")

    gone = sorted(withdrawn(state, auction))
    if gone:
        st.caption("Withdrawn: " + ", ".join(gone))

    st.caption("Bidding is OPEN" if state["open"] else "Bidding is CLOSED")
    if st.button("Refresh"):
        st.rerun()


# --------------------------------------------------------------------------
# INSTRUCTOR VIEW
# --------------------------------------------------------------------------

def instructor_view(state):
    st.title("Instructor controls")

    a = st.selectbox("Auction", list(AUCTIONS), key="selauc",
                     format_func=lambda k: f"{AUCTIONS[k]['name']} — {AUCTIONS[k]['item']}",
                     index=list(AUCTIONS).index(state["auction"]))
    if a != state["auction"]:
        if st.button(f"Switch to {AUCTIONS[a]['name']}"):
            state["auction"] = a
            state["round"] = 0
            state["open"] = False
            save(state)
            st.rerun()

    auction = state["auction"]
    st.subheader(f"{AUCTIONS[auction]['name']} — round {state['round']} — "
                 + ("OPEN" if state["open"] else "CLOSED"))

    c1, c2, c3 = st.columns(3)
    if c1.button("Open next round", type="primary"):
        state["round"] += 1
        state["open"] = True
        save(state)
        st.rerun()
    if c2.button("Close round"):
        state["open"] = False
        save(state)
        st.rerun()
    if c3.button("Reopen this round"):
        state["open"] = True
        save(state)
        st.rerun()

    if state["open"]:
        st.info(f"Round {state['round']} is open. The ladder below still shows "
                f"round {visible_round(state)}. Close the round to update it.")

    st.divider()
    rows = ladder(state, auction)
    cfg = AUCTIONS[auction]
    if rows:
        st.write("**Live ladder (with costs — instructor only)**")
        st.dataframe([{"Position": f"L{i}", "Team": c, "Bid": money(p),
                       "Cost": money(cfg["teams"][c]),
                       "Margin": money(p - cfg["teams"][c])}
                      for i, (c, p) in enumerate(rows, start=1)],
                     hide_index=True, width="stretch")
    gone = sorted(withdrawn(state, auction))
    if gone:
        st.write("**Withdrawn:** " + ", ".join(f"{c} (cost {money(cfg['teams'][c])})" for c in gone))

    st.divider()
    st.write("**This round's submissions**")
    this_round = [b for b in state["bids"]
                  if b["auction"] == auction and b["round"] == state["round"]]
    if this_round:
        st.dataframe([{"Team": b["code"], "Names": b["names"],
                       "Bidding": "Yes" if b["bidding"] else "No",
                       "Bid": money(b["bid"]) if b["bid"] is not None else "—",
                       "Status": b["status"], "Time": b["ts"][11:]}
                      for b in this_round], hide_index=True, width="stretch")
        yet = [c for c in cfg["teams"]
               if c not in {b["code"] for b in this_round} and c not in gone]
        if yet:
            st.caption("Yet to submit: " + ", ".join(sorted(yet)))
    else:
        st.caption("Nothing submitted yet this round.")

    preds = [p for p in state["predictions"] if p["auction"] == auction]
    if preds:
        st.divider()
        st.write("**Predictions**")
        st.dataframe([{"Round": p["round"], "Team": p["code"],
                       "Predicted L1": money(p["value"])} for p in preds],
                     hide_index=True, width="stretch")

    st.divider()
    with st.expander("Reveal and export"):
        for k, c2 in AUCTIONS.items():
            rr = ladder(state, k)
            if rr:
                win, price = rr[0]
                st.write(f"**{c2['name']}** — winner {win} at {money(price)} "
                         f"{c2['unit']}, cost {money(c2['teams'][win])}, "
                         f"margin {money(price - c2['teams'][win])} {c2['unit']}")
            else:
                st.write(f"**{c2['name']}** — not run yet")
        d1, d2, d3 = st.columns(3)
        d1.download_button("Bids (CSV)", data=bids_csv(state),
                           file_name="auction_bids.csv", mime="text/csv")
        d2.download_button("Predictions (CSV)", data=predictions_csv(state),
                           file_name="auction_predictions.csv", mime="text/csv")
        d3.download_button("Everything (JSON backup)",
                           data=json.dumps(state, indent=2),
                           file_name="auction_data.json", mime="application/json")

    st.divider()
    with st.expander("Danger zone"):
        st.caption("Clears every bid and prediction in all three auctions.")
        if st.text_input("Type RESET to confirm") == "RESET":
            if st.button("Reset everything"):
                new = blank_state()
                state.clear()
                state.update(new)
                save(state)
                st.rerun()


# --------------------------------------------------------------------------
# MAIN
# --------------------------------------------------------------------------

def main():
    st.set_page_config(page_title="SunPulp Reverse Auction", page_icon="🔨",
                       layout="centered")
    state = get_state()

    role = st.sidebar.radio("View", ["Bidder", "Projector", "Instructor"])
    st.sidebar.caption("Students: leave this on Bidder.")

    if role == "Bidder":
        bidder_view(state)
    elif role == "Projector":
        if st.session_state.get("proj_ok"):
            projector_view(state)
        else:
            pw = st.sidebar.text_input("Projector password", type="password")
            if pw == PROJECTOR_PASSWORD:
                st.session_state["proj_ok"] = True
                st.rerun()
            else:
                st.info("This view is for the classroom screen only.")
    else:
        pw = st.sidebar.text_input("Password", type="password")
        if pw == INSTRUCTOR_PASSWORD:
            instructor_view(state)
        else:
            st.info("Instructor access only.")


main()
