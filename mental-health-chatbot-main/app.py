from flask import Flask, render_template, request, jsonify
import json, os, requests
from dotenv import load_dotenv
import uuid
import re
from flask import send_file

# --- Load environment variables ---
load_dotenv()
PERPLEXITY_KEY = os.getenv("PERPLEXITY_API_KEY")

app = Flask(__name__)

# --- Chat history ---
HISTORY_FILE = "chat_history.json"
if os.path.exists(HISTORY_FILE):
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        chat_history = json.load(f)
else:
    chat_history = []

# --- System prompt ---
system_prompt = """
You are Dilse, a friendly, caring, and empathetic mental health chatbot for students.
Always respond in a supportive, concise, and non-judgmental way. Keep language simple and student-focused.
Do NOT address the user by their name except once when you first meet them (use the name only in the first greeting).
Always end with a short follow-up question to keep the conversation going.
"""

# --- Ask AI / Perplexity ---
def ask_perplexity(user_input):
    if not PERPLEXITY_KEY:
        return "(Offline Mode) API key not set."

    messages = [{"role": "system", "content": system_prompt}]
    for msg in chat_history[-10:]:
        if msg["role"] in ["user", "assistant"]:
            messages.append(msg)
    messages.append({"role": "user", "content": user_input})

    headers = {"Authorization": f"Bearer {PERPLEXITY_KEY}", "Content-Type": "application/json"}
    payload = {"model": "sonar-pro", "messages": messages, "temperature": 0.7, "max_tokens": 250}

    try:
        r = requests.post("https://api.perplexity.ai/chat/completions", headers=headers, json=payload)
        if r.status_code == 200:
            result = r.json()
            if "choices" in result and len(result["choices"]) > 0:
                return result["choices"][0]["message"]["content"]
            else:
                return "(Offline Mode) Perplexity API returned no choices."
        else:
            print("Perplexity API error:", r.status_code, r.text)
            return f"(Offline Mode) Perplexity API error: {r.status_code}"
    except Exception as e:
        print("Perplexity API exception:", e)
        return "(Offline Mode) Could not connect to Perplexity API."

# --- Format AI reply to HTML ---
def format_reply(ai_text, max_sentences: int = 7, followup: str = None, end_conversation: bool = False):
    """
    Clean AI text, limit to `max_sentences`, convert simple markdown (bold)
    and list lines to safe HTML paragraphs / lists.
    If end_conversation is True, do not append any follow-up question.
    """
    import re

    if not ai_text:
        return "<p>Sorry, I couldn't generate a reply right now.</p>"

    # remove citation-style markers and convert simple markdown
    text = re.sub(r'(?:\s*\[\d+\])+', '', ai_text)
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = text.replace('*', '')

    # split into sentences (keeps punctuation)
    sentences = re.split(r'(?<=[\.!\?…])\s+', text.strip())
    # filter out empty
    sentences = [s.strip() for s in sentences if s.strip()]

    truncated = sentences[:max_sentences]
    truncated_text = " ".join(truncated).strip()

    # Ensure we end cleanly with punctuation
    if truncated_text and truncated_text[-1] not in ".!?…":
        truncated_text = truncated_text + "."

    # if original had more sentences, append an ellipsis to show continuation
    if len(sentences) > max_sentences:
        truncated_text = truncated_text.rstrip() + " …"

    # ensure there is a follow-up question unless this is an end-of-conversation reply
    has_question = bool(re.search(r'\?\s*$', truncated_text))
    if not has_question and not end_conversation:
        if followup:
            truncated_text = truncated_text + " " + followup
        else:
            truncated_text = truncated_text + " Would you like to tell me more?"

    # Convert simple lists / paragraphs into HTML
    lines = truncated_text.splitlines()
    out = []
    in_list = False
    for line in lines:
        line = line.strip()
        if re.match(r'^(-|\d+\.)\s+', line):
            if not in_list:
                in_list = True
                out.append("<ul>")
            item = re.sub(r'^(-|\d+\.)\s+', '', line)
            out.append(f'<li>{item}</li>')
        else:
            if in_list:
                out.append("</ul>")
                in_list = False
            if line:
                out.append(f"<p>{line}</p>")
    if in_list:
        out.append("</ul>")

    html = "\n".join(out) if out else f"<p>{truncated_text}</p>"
    return html

INVALID_NAMES = {
    "no","yes","ok","okay","maybe","nah","nope",
    "i","me","my","mine","student","everyone","none",
    # common emotion/adjective words — don't treat these as names
    "happy","sad","angry","anxious","excited","stressed","calm","lonely",
    "relaxed","tired","bored","scared","afraid","depressed","upset",
    # common short replies / fillers/affirmations that should never become names
    "yeah","yep","yup","sure","right","okey","okeydokey","kk","k","thanks","thankyou","thank","cool","nice"
}

# --- Persisted user name ---
USER_FILE = "user.json"
user_data = {}
if os.path.exists(USER_FILE):
    try:
        with open(USER_FILE, "r", encoding="utf-8") as f:
            user_data = json.load(f) or {}
    except Exception:
        user_data = {}
    # auto-clear invalid saved name
    saved = (user_data.get("name") or "").strip().lower()
    if saved in INVALID_NAMES:
        try:
            os.remove(USER_FILE)
        except Exception:
            pass
        user_data = {}

def set_user_name(name: str):
    global user_data
    if not name:
        return False
    name_clean = name.strip()
    # reject obviously invalid tokens
    if name_clean.lower() in INVALID_NAMES or len(name_clean) < 2:
        return False
    name_clean = name_clean.capitalize()
    user_data = {"name": name_clean, "greeted": False}
    try:
        with open(USER_FILE, "w", encoding="utf-8") as f:
            json.dump(user_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("Could not save user name:", e)
    return True

def get_user_name():
    # always reload to avoid stale memory
    if os.path.exists(USER_FILE):
        try:
            with open(USER_FILE, "r", encoding="utf-8") as f:
                d = json.load(f) or {}
                return d.get("name")
        except Exception:
            pass
    return user_data.get("name")

def set_user_greeted():
    global user_data
    user_data["greeted"] = True
    try:
        with open(USER_FILE, "w", encoding="utf-8") as f:
            json.dump(user_data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def user_was_greeted():
    if os.path.exists(USER_FILE):
        try:
            with open(USER_FILE, "r", encoding="utf-8") as f:
                d = json.load(f) or {}
                return bool(d.get("greeted"))
        except Exception:
            pass
    return bool(user_data.get("greeted"))

# --- Chatbot response ---
def chatbot_response(user_input):
    """
    Persist name if detected. Greet by name only once; afterwards do NOT address user by name.
    Prompt AI to produce short, student-focused replies (<=7 sentences) and end with a follow-up question.
    """
    # reload persisted name
    user_name = get_user_name()

    # Try detect + persist name (first time)
    if not user_name:
        detected = store_name(user_input)
        if detected:
            set_user_name(detected)
            # greet once immediately (do not call AI for this simple greeting)
            set_user_greeted()  # mark greeted so future replies won't use name
            reply_text = f"Nice to meet you, {detected}! How are you feeling today?"
            return format_reply(reply_text)

    # Build AI instruction: explicitly tell AI not to use name if already greeted
    instruction = (
        "You are Dilse, a friendly, caring, empathetic mental health chatbot for students. "
        "Answer supportively and concisely (limit to 7 sentences). "
        "End with a short follow-up question to keep the conversation going. "
    )
    if user_was_greeted():
        instruction += "Do NOT address the user by name in your reply."
    else:
        instruction += "You may use the user's name once to greet them, but do not use the name repeatedly."

    name_line = f"User name: {user_name}." if user_name and not user_was_greeted() else ""

    final_prompt = f"{system_prompt}\n{instruction}\n{name_line}\nUser: {user_input}"

    ai_text = ask_perplexity(final_prompt)

    # build a contextual followup based on user's latest message
    followup = choose_followup(user_input)

    # format and enforce sentence limit, append followup if needed
    html = format_reply(ai_text, max_sentences=9, followup=followup)

    # After generating a reply, if user wasn't greeted but we included a greeting, mark greeted.
    # Conservative approach: if user_name exists and not greeted, mark greeted so AI won't reuse it.
    if user_name and not user_was_greeted():
        set_user_greeted()

    # save to chat history (existing logic)
    try:
        chat_history.append({"role": "user", "content": user_input, **({"name": user_name} if user_name else {})})
        chat_history.append({"role": "assistant", "content": ai_text})
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(chat_history, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    return html

# --- Planner storage ---
PLANNER_FILE = "planner.json"
if os.path.exists(PLANNER_FILE):
    with open(PLANNER_FILE, "r", encoding="utf-8") as f:
        try:
            planner_items = json.load(f)
        except Exception:
            planner_items = []
else:
    planner_items = []

def save_planner():
    with open(PLANNER_FILE, "w", encoding="utf-8") as f:
        json.dump(planner_items, f, ensure_ascii=False, indent=2)

# --- Planner API ---
@app.route("/planner_items", methods=["GET"])
def get_planner_items():
    return jsonify(planner_items)

@app.route("/planner_items", methods=["POST"])
def add_planner_item():
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"error": "Title required"}), 400
    item = {
        "id": str(uuid.uuid4()),
        "title": title,
        "date": data.get("date", "").strip(),
        "time": data.get("time", "").strip(),
        "notes": data.get("notes", "").strip(),
        "completed": False
    }
    planner_items.append(item)
    save_planner()
    return jsonify(item), 201

@app.route("/planner_items/<item_id>", methods=["DELETE"])
def delete_planner_item(item_id):
    global planner_items
    planner_items = [i for i in planner_items if i.get("id") != item_id]
    save_planner()
    return jsonify({"ok": True})

@app.route("/planner_items/<item_id>", methods=["PATCH"])
def update_planner_item(item_id):
    data = request.get_json(silent=True) or {}
    for it in planner_items:
        if it.get("id") == item_id:
            if "completed" in data:
                it["completed"] = bool(data["completed"])
            if "title" in data: it["title"] = (data.get("title") or "").strip()
            if "date" in data: it["date"] = (data.get("date") or "").strip()
            if "time" in data: it["time"] = (data.get("time") or "").strip()
            if "notes" in data: it["notes"] = (data.get("notes") or "").strip()
            save_planner()
            return jsonify(it)
    return jsonify({"error": "Not found"}), 404

# Download planner file (returns planner.json as attachment)
@app.route("/download_planner", methods=["GET"])
def download_planner():
    # return the same structured plain-text export so /download_planner does NOT send raw JSON
    return download_planner_text()

# new: download planner as structured plain text
@app.route("/download_planner_text", methods=["GET"])
def download_planner_text():
    # Build a readable plain-text export of planner_items
    lines = []
    if not planner_items:
        lines.append("Planner is empty.")
    else:
        for idx, it in enumerate(planner_items, start=1):
            lines.append(f"Item {idx}")
            lines.append(f"Title : {it.get('title','')}")
            lines.append(f"Date  : {it.get('date','')}")
            lines.append(f"Time  : {it.get('time','')}")
            notes = (it.get('notes') or "").strip()
            if notes:
                # preserve newlines in notes by indenting subsequent lines
                note_lines = notes.splitlines()
                lines.append(f"Notes : {note_lines[0]}")
                for nl in note_lines[1:]:
                    lines.append(f"        {nl}")
            else:
                lines.append("Notes : ")
            lines.append(f"Status: {'Completed' if it.get('completed') else 'Pending'}")
            lines.append("-" * 40)
    body = "\n".join(lines) + "\n"
    headers = {
        "Content-Type": "text/plain; charset=utf-8",
        "Content-Disposition": 'attachment; filename="planner.txt"'
    }
    return (body, 200, headers)

# --- Flask routes ---
@app.route("/")
def home():
    return render_template("index.html")

@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}
    user_input = data.get("message", "").strip()
    if not user_input:
        return jsonify({"reply": "Please enter a message."})

    response = chatbot_response(user_input)
    return jsonify({"reply": response})

@app.route("/planner")
def planner_page():
    # Render a separate planner page (new template)
    return render_template("planner.html")

def store_name(user_input: str):
    """
    Extracts and cleans a likely user name from input text.
    Handles formats like 'my name is X', 'I am X', "I'm X", or single-word names.
    Rejects values in INVALID_NAMES and common filler words.
    """
    if not user_input:
        return None

    text = user_input.strip()

    # common patterns: "my name is X", "call me X", "I'm X", "I am X"
    patterns = [
        r"\bmy\s+name\s+is\s+([A-Za-z][A-Za-z'\-]*)\b",
        r"\bcall\s+me\s+([A-Za-z][A-ZaZ'\-]*)\b",
        r"\bi\s*(?:'m|am)\s+([A-Za-z][A-Za-z'\-]*)\b"
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            candidate = re.sub(r"[^A-Za-z'\-]", "", match.group(1)).strip().capitalize()
            if candidate and candidate.lower() not in INVALID_NAMES:
                return candidate

    # single-word input -> treat as name only if alphabetic, reasonable length,
    # not in INVALID_NAMES, and likely a real name (simple vowel check)
    tokens = text.split()
    if len(tokens) == 1:
        token = re.sub(r"[^A-Za-z'\-]", "", tokens[0]).strip()
        if token and token.isalpha() and 2 <= len(token) <= 30 and token.lower() not in INVALID_NAMES:
            # require at least one vowel OR allow very short names (<=3) to accommodate e.g. "Li"
            if re.search(r"[aeiou]", token, flags=re.I) or len(token) <= 3:
                return token.capitalize()

    return None

def choose_followup(user_input: str):
    """
    Return a short student-focused follow-up question based on user_input.
    Keep it concise and actionable.
    """
    if not user_input:
        return "Would you like to tell me more or try a short grounding exercise?"

    u = user_input.lower()

    exams = ["exam", "exams", "test", "tests", "grade", "grades", "marks", "result", "results"]
    stress = ["stress", "stressed", "stressing", "overwhelmed", "pressure", "deadline"]
    anxious = ["anxious", "anxiety", "worried", "worried about"]
    happy = ["happy", "excited", "great", "celebrate", "good marks", "good grade", "got"]
    sleep = ["sleep", "tired", "rest", "insomnia"]
    social = ["friend", "friends", "relationship", "peer", "classmate", "roommate"]

    if any(k in u for k in exams):
        return "Congrats — would you like tips to keep the momentum or plan next study steps?"
    if any(k in u for k in happy):
        return "That’s wonderful — want ideas to celebrate or channels to share this with friends?"
    if any(k in u for k in anxious) or any(k in u for k in stress):
        return "Would you like a short breathing exercise now or a few quick strategies to manage this stress?"
    if any(k in u for k in sleep):
        return "Would you like some quick sleep tips you can try tonight?"
    if any(k in u for k in social):
        return "Do you want help thinking through how to talk to them or what to say?"
    # default
    return "Would you like to tell me more, or try a short grounding exercise?"

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    # debug=False in production
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG", "0") == "1")
