# Putting The Tape on the internet

Everything is committed and ready. These are the only steps left, and they all
happen in a browser. Nothing here costs money.

The result is a **static site rebuilt on a schedule**, not a live server. That
matters: the page never fetches on behalf of a visitor, so one build serves
everyone and the SEC rate limit is respected no matter how much traffic arrives.

---

## 1. Make a GitHub account

<https://github.com/signup> — free. Skip if you have one.

## 2. Create an empty repository

<https://github.com/new>

- **Repository name:** `the-tape`
- **Public** (GitHub Pages needs this on the free plan)
- **Do NOT** tick "Add a README" — the repo must be empty or the push is refused

Press **Create repository**. Leave the page open; you need the URL from it.

## 3. Push the code

Open the folder `C:\Users\edoma\smart-money` in a terminal and run these,
replacing `YOURNAME` with your GitHub username:

```bash
git remote add origin https://github.com/YOURNAME/the-tape.git
git push -u origin main
```

GitHub will ask you to sign in. If it wants a password, it means a **token**:
create one at <https://github.com/settings/tokens> (classic, scope `repo`) and
paste that instead.

## 4. Turn on Pages

In your new repo: **Settings → Pages → Build and deployment → Source**, choose
**GitHub Actions**. That is the whole configuration.

## 5. Add your contact address

SEC asks automated clients to identify themselves and throttles those that
don't. It lives in a repository variable so it is not baked into public code.

**Settings → Secrets and variables → Actions → Variables tab → New variable**

- Name: `SEC_CONTACT`
- Value: your email address

## 6. Run the first build

**Actions** tab → **Build and publish** → **Run workflow**.

It takes 10–20 minutes, mostly downloading congressional disclosure PDFs one at
a time. When it goes green, the site is live at:

```
https://YOURNAME.github.io/the-tape
```

After this it rebuilds itself **every weekday at 11:30 UTC**. You never touch it
again.

---

## Changing things

| You want to | Do this |
|---|---|
| Rebuild right now | Actions → Build and publish → Run workflow |
| Change how far back it looks | Edit `INSIDER_DAYS` / `CONGRESS_DAYS` in `.github/workflows/build.yml` |
| Change the schedule | Edit the `cron:` line in the same file |
| Track different funds | Edit `INSTITUTIONS` in `smartmoney/collect.py` |
| Follow a different person | Edit `WATCHLIST` in `smartmoney/people.py` |
| Take it offline | Settings → Pages → set Source to "None". Or delete the repo. |

Any change: commit and push, and the site rebuilds on its own.

## A custom domain

If you buy one (~£10/year), point a CNAME at `YOURNAME.github.io` and set it
under **Settings → Pages → Custom domain**. Optional — the free URL works fine.

---

## Before you publish, know what you are publishing

- **The repo is public.** Anyone can read the code. That is fine — there are no
  keys in it, and your email sits in a repository variable, not in the source.
- **The site is public and Google can index it.** It carries a
  "not investment advice" disclaimer and publishes the backtest result showing
  no edge was found. Do not remove either. A public page that shows trading
  signals while hiding that they failed testing is the thing to avoid.
- **The data is reproduced as filed.** Filings contain errors, and the parser
  can misread an unusual PDF layout. The site links back to the source
  documents; treat those as the truth.
- **Congressional disclosures name real people**, taken from the official public
  record. Publishing them is ordinary — this is what the STOCK Act exists for —
  but keep the framing factual and let the filings speak.
