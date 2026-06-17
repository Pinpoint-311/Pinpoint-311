# Pinpoint 311 — Siri Voice Report Shortcut: Complete Build & Setup Guide

This guide explains, step by step, how to get the voice reporting shortcut working.
**No coding and no backend changes are required.** Everything happens in the iPhone
**Shortcuts** app, talking to API endpoints that already exist in your Pinpoint instance.

There are two paths:

- **Path A — Import the ready-made file** (fastest; may need small fix-ups).
- **Path B — Build it by hand** (reliable; ~20 minutes; this is the supported Apple way).

If Path A imports and runs, you're done. If it complains, use Path B — it always works.

---

## Before you start (one-time setup)

1. On the iPhone, open **Settings → Shortcuts**.
2. Turn ON **Allow Untrusted Shortcuts**.
   - If the toggle is greyed out, open the **Shortcuts** app, run any built-in shortcut
     once, then return to Settings — it will be enabled.
3. Know your municipality's Pinpoint web address, e.g. `https://yourtown.pinpoint311.org`.
   We'll call this your **Base URL**. Do not put a slash at the end.

---

## Path A — Import the ready-made file

1. Get the file `PinpointReport.shortcut` onto the iPhone (AirDrop, email, or iCloud Drive).
2. Open the **Files** app, tap `PinpointReport.shortcut`.
3. Tap **Add Shortcut** (you may need to scroll down and tap **Add Untrusted Shortcut**).
4. When prompted, paste your **Base URL**.
5. Open **Shortcuts**, find **PinpointReport**, tap it to run a test.

If it runs end-to-end and you hear "Your report has been submitted," you're finished —
skip to **Testing** and **Distribution** below.

If import fails or an action shows an error, note which step it names and switch to Path B.

---

## Path B — Build it by hand (the reliable way)

Open **Shortcuts → "+" (top right)** to create a new shortcut. Tap its name at the top,
choose **Rename**, and call it **Report an Issue**. Now add the actions below **in order**.

To add an action: tap the **search bar** at the bottom, type the action name, tap it.
"Variable" means a stored value you'll reuse later. To insert a variable into a text field,
tap the field, then tap **Select Variable** (or the **Magic Variable** wand) and pick it.

> Tip: After many actions you'll tap **"Set Variable"** to name the result. When you do,
> rename it exactly as written (e.g. `BaseURL`) so later steps line up.

### Section 1 — Setup and location

1. **Text**
   - Type your Base URL, e.g. `https://yourtown.pinpoint311.org`
2. **Set Variable**
   - Name it **BaseURL** (set to the Text from step 1).
3. **Get Current Location**
4. **Set Variable** → name it **TriggerLocation**.
5. **Get Details of Locations**
   - Get: **Latitude**, from **TriggerLocation**.
6. **Set Variable** → name it **Lat**.
7. **Get Details of Locations**
   - Get: **Longitude**, from **TriggerLocation**.
8. **Set Variable** → name it **Lng**.

### Section 2 — Fetch the categories and questions (the dynamic part)

9. **Text**
   - Type: tap the field, insert the **BaseURL** variable, then type `/api/services/`
     right after it. Result looks like `[BaseURL]/api/services/`.
10. **Get Contents of URL**
    - URL: the **Text** from step 9.
    - Method: **GET** (this is the default).
11. **Set Variable** → name it **Services**.

### Section 3 — Pick a category by voice

12. **Choose from List**
    - List: the **Services** variable.
    - Prompt: `What type of issue are you reporting?`
    - (Siri will read the choices aloud when run hands-free.)
13. **Set Variable** → name it **ChosenService**.
14. **Get Dictionary Value**
    - Get **Value** for key `service_code` in **ChosenService**.
15. **Set Variable** → name it **ServiceCode**.
16. **Get Dictionary Value**
    - Get **Value** for key `routing_config` in **ChosenService**.
17. **Set Variable** → name it **RoutingConfig**.
18. **Get Dictionary Value**
    - Get **Value** for key `custom_questions` in **RoutingConfig**.
19. **Set Variable** → name it **Questions**.

### Section 4 — Start an empty answers dictionary

20. **Dictionary**
    - Leave it empty (don't add any rows).
21. **Set Variable** → name it **Answers**.

### Section 5 — Ask every question dynamically (the loop)

22. **Repeat with Each**
    - Items: the **Questions** variable.
    - Everything from here until the matching **End Repeat** happens once per question.
    - Inside the loop, **Repeat Item** means "the current question."

    Add these INSIDE the repeat block:

    23. **Get Dictionary Value**
        - Get **Value** for key `label` in **Repeat Item**.
    24. **Set Variable** → name it **QLabel**.
    25. **Speak Text**
        - Text: insert the **QLabel** variable. (Siri reads the question aloud.)
    26. **Ask for Input**
        - Input type: **Text**.
        - Prompt: insert the **QLabel** variable.
        - (The resident answers by voice; Siri transcribes it.)
    27. **Set Variable** → name it **QAnswer**.
    28. **Set Dictionary Value**
        - Dictionary: the **Answers** variable.
        - Key: insert the **QLabel** variable.
        - Value: insert the **QAnswer** variable.
    29. **Set Variable** → name it **Answers** (overwrites with the updated dictionary).

30. **End Repeat** (this appears automatically; make sure steps 23–29 are inside it).

### Section 6 — Description and email

31. **Dictate Text**
    - This is the spoken free description.
    - (Optional: afterward add a **Text** action that combines this with your GPS notes,
      e.g. "…[voice report near {address}]", then Set Variable **Description** from that.
      Otherwise just Set Variable **Description** from the Dictate Text below.)
32. **Set Variable** → name it **Description**.
33. **Ask for Input**
    - Input type: **Text**.
    - Prompt: `What is your email address?`
34. **Set Variable** → name it **Email**.

### Section 7 — Build the report and submit

35. **Dictionary** — add these rows:
    | Key | Type | Value (insert as variable) |
    |-----|------|-----------------------------|
    | `service_code` | Text | **ServiceCode** |
    | `description` | Text | **Description** |
    | `email` | Text | **Email** |
    | `lat` | Number | **Lat** |
    | `long` | Number | **Lng** |
    | `custom_fields` | Dictionary | **Answers** |
36. **Set Variable** → name it **RequestBody**.
37. **Text**
    - Insert the **BaseURL** variable, then type `/api/open311/v2/requests.json`.
38. **Get Contents of URL**
    - URL: the **Text** from step 37.
    - Method: **POST**.
    - Request Body: **JSON**.
    - Tap **Add new field → Dictionary**? No — instead set the body to the **RequestBody**
      variable: choose **Request Body = JSON**, then in the JSON area insert the
      **RequestBody** variable. (Header `Content-Type: application/json` is added automatically
      for JSON bodies.)
39. **Set Variable** → name it **SubmitResponse**.

### Section 8 — Confirm out loud

40. **Get Dictionary Value**
    - Get **Value** for key `service_request_id` in **SubmitResponse**.
41. **Set Variable** → name it **TrackingID**.
42. **Speak Text**
    - Text: `Your report has been submitted. Tracking number ` then insert **TrackingID**.

You're done. Tap the **play ▶︎** button at the bottom to test.

---

## Important rules the API enforces (so your test doesn't fail)

- **Email is required** and must look like a real address (`name@domain.com`).
- **Description must be at least 10 characters.** Speak a real sentence.
- **Photos** are capped at 3. (Optional: add **Take Photo → Base64 Encode**, then add a
  `media_urls` row of type **Array** containing that encoded text.)
- Custom question answers are stored under the question's **label** — the loop already does this.

---

## Add the voice trigger ("Hey Siri")

1. In the shortcut, tap the **(i)** / settings icon → **Add to Siri** (or it's automatic).
2. The phrase is the shortcut's name. Rename the shortcut to something natural like
   **Report an Issue** so you can say **"Hey Siri, Report an Issue."**

## CarPlay

- No extra work. The shortcut runs in CarPlay automatically through the car mic/speakers.
- Optional: in Shortcuts, pin it so it shows as a **"Report Issue"** tile on the CarPlay screen.

---

## Testing checklist

1. Run it parked, with a strong signal.
2. Confirm Siri reads your real categories aloud (proves `/api/services/` is reached).
3. Confirm it asks each custom question for the category you pick.
4. After submitting, open your **staff dashboard** — the new request should appear with the
   location, description, and custom answers.
5. Check the confirmation email arrived.

If something fails, the usual causes are: Base URL has a trailing slash (remove it),
email left blank, or description shorter than 10 characters.

---

## Distribution to residents (optional)

1. In Shortcuts, tap **(i) → Share → Copy iCloud Link**.
2. Put that link on the town website, newsletter, and social media.
3. Generate a **QR code** from the link for flyers, town hall, and libraries.
4. Residents tap once to install — it appears in Siri and CarPlay immediately.

> Note: each municipality ships its own copy with its own Base URL, because the shortcut
> submits to one specific Pinpoint instance.
