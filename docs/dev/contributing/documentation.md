# Documentation

One of the most valuable ways you can contribute to Yesterdays is by reviewing and contributing to our documentation.

The source for this documentation site lives in [the Yesterdays git repository](https://github.com/MapRVA/yesterdays), in the `/docs/` folder.
It is additionally configured in `/zensical.toml`.

## Hosting locally

Use the following command to host this site locally:

```
uv run zensical serve
```

The site will be live at `http://localhost:8000`.
Changes in the `/docs/` directory should trigger automatic refreshes of the site as you view it in your browser.

Please note that the main Yesterdays site also uses port 8000 by default, so it is not possible to run both development servers at once without configuring one of them to use a different port.

## Code blocks

We strive to provide all code examples in Python and R.
You may open an issue in our repository to request another language.

Code blocks are formatted using a variety of tricks [as documented by Zensical](https://zensical.org/docs/authoring/code-blocks/).
