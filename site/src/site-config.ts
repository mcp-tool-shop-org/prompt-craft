import type { SiteConfig } from '@mcptoolshop/site-theme';

export const config: SiteConfig = {
  title: 'prompt-craft',
  description:
    'Say what the picture must contain. Check that it does. Refuse when it does not. A typed contract of depictable claims drives both the prompt and the gate that verifies the pixels.',
  logoBadge: 'PC',
  brandName: 'prompt-craft',
  repoUrl: 'https://github.com/mcp-tool-shop-org/prompt-craft',
  footerText:
    'MIT Licensed — built by <a href="https://github.com/mcp-tool-shop-org" style="color:var(--color-muted);text-decoration:underline">mcp-tool-shop-org</a>',

  hero: {
    badge: 'v0.2.0 · pre-1.0, deliberately',
    headline: 'Say what the picture must contain.',
    headlineAccent: 'Then check that it does.',
    description:
      'A generative pipeline will hand you a hero with the wrong face and report success, because nothing looked. prompt-craft replaces the opaque prompt with a typed contract of depictable claims, uses that same list to write the prompt and to check the pixels, and blocks the asset when a required claim is not there.',
    primaryCta: { href: '#usage', label: 'Get started' },
    secondaryCta: { href: 'handbook/', label: 'Read the Handbook' },
    previews: [
      { label: 'Install', code: 'pip install -e ".[dev]"' },
      { label: 'Run the loop', code: 'pcraft demo        # end-to-end, no GPU' },
      { label: 'Check an image', code: 'pcraft gate hero.png' },
    ],
  },

  sections: [
    {
      kind: 'features',
      id: 'features',
      title: 'What it actually does',
      subtitle: 'One atom list, used twice — to write the prompt, and to check the result.',
      features: [
        {
          title: 'The same list, twice',
          desc: 'The contract writes the prompt and gates the pixels from one source, so the thing you asked for is the thing that gets verified. That is what closes the loop an opaque prompt leaves open.',
        },
        {
          title: 'A different family checks it',
          desc: 'The verifier is never the same model family as the generator, enforced by a guard that refuses to run otherwise. A model is a poor judge of its own output.',
        },
        {
          title: 'It can say "I could not check"',
          desc: 'Four distinct exit codes separate a failed claim from an unreadable input from an unavailable verifier. Merging those is why browsers soft-fail certificate revocation.',
        },
        {
          title: 'Absence is verified, not requested',
          desc: 'Anti-constraints are checked on the pixels rather than dropped into a negative prompt, because negative prompts leave residual features and fall to paraphrase.',
        },
        {
          title: 'Fail-closed inheritance',
          desc: 'A character contract extends a faction and may raise a requirement — never relax or silently drop one it inherited.',
        },
        {
          title: 'Mutation-tested decisions',
          desc: 'The eleven compound predicates in the core are mutation-tested: 20 of 21 mutants killed, and the survivor is named rather than hidden.',
        },
      ],
    },
    {
      kind: 'code-cards',
      id: 'usage',
      title: 'Usage',
      cards: [
        {
          title: 'Install — the core is GPU-free',
          code: 'pip install -e ".[dev]"\npcraft --help',
        },
        {
          title: 'Run the whole loop with no GPU',
          code: 'pcraft demo\n\n# synth -> generate -> gate -> repair -> bind,\n# against deterministic stubs',
        },
        {
          title: 'Check an image against a contract',
          code: 'pcraft gate hero.png\n\n# 0 passed - 2 a required atom failed\n# 3 unconfirmed - 4 could not run',
        },
        {
          title: 'Re-read what was bound',
          code: 'pcraft replay records/hero.json\n\n# contract hash, generator + seed,\n# verifier version, per-atom transcript',
        },
      ],
    },
  ],
};
