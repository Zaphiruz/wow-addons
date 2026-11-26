# The Gander data Worker

A small Cloudflare Worker. The page in `site/` sends it one submission block
at a time, and it files each as an issue with the `gander-data` label, so
players don't need a GitHub account. From there the "Gander data" workflow
checks it like any other submission.

What it does, and guards against, is described at the top of
`gander-worker.mjs`. Its tests: `node --test worker/test/worker.test.mjs`
(they also run with `python mods/classic/tools/run_tests.py`).

## Setting it up (once, by the repository's owner)

It runs on Cloudflare's free plan. You need a Cloudflare account and Node.js.

1. **Make a GitHub token that can only open issues here.** On GitHub: Settings,
   Developer settings, Personal access tokens, Fine-grained tokens, Generate
   new token.
   - Repository access: Only select repositories, `wow-addons`.
   - Permissions: Repository permissions, Issues: Read and write. Nothing else.
   - Copy the token. It is shown once.
2. **Log in to Cloudflare.** A browser window opens. Run this and every
   command below from the repository's top folder:

   ```
   npx wrangler login
   ```

   Keep the `--config worker/wrangler.toml` part on the commands that have
   it. Without it wrangler makes settings of its own and publishes the `site`
   folder as a different Worker.

3. **Deploy.** The first time, it asks you to pick a `workers.dev` name. At the
   end it prints the Worker's address, like
   `https://gander-data.<your-name>.workers.dev`:

   ```
   npx wrangler deploy --config worker/wrangler.toml
   ```

4. **Save the two secrets.** Each command asks for the value and hides what
   you type. The salt is any long random text: nobody needs to remember it.

   ```
   npx wrangler secret put GITHUB_TOKEN --config worker/wrangler.toml
   npx wrangler secret put SENDER_SALT --config worker/wrangler.toml
   ```

5. **Check it.** Open the Worker's address in a browser. It should show
   `{"ok":true,"service":"gander-data","ready":true}`.
6. **Tell the page.** Put the address in `site/config.js`
   (`window.GANDER_SEND_URL`) and push. The page then shows a Send button and
   the box for the block from `/gander send`.

## Keeping it running

- When the code changes, deploy again:
  `npx wrangler deploy --config worker/wrangler.toml`. The secrets stay.
- When the token expires, make a new one and run
  `npx wrangler secret put GITHUB_TOKEN --config worker/wrangler.toml` again.
  Until then the page tells players it couldn't reach the database, and
  they can still send by hand.
- Changing `SENDER_SALT` makes every sender look new. Data that is waiting for
  a second sender could then be confirmed by the same person, so leave it.
- The token and the salt live only in Cloudflare. Never put them in a file.
