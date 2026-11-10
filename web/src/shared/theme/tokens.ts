/** Every colour, size, space, radius and duration the dashboard uses. Components never hard-code these. */
export const color = {
  paper: "#F4F5F7",
  card: "#FFFFFF",
  ink: "#18202E",
  muted: "#5C6575",
  line: "#D9DDE4",
  panel: "#E7EAEF",
  registry: "#0F7C80", // facts from a registry: the trusted source
  registrySoft: "#DDF0F0",
  listed: "#B4421A", // a sanctions listing in force
  listedSoft: "#F7E3DA",
  pep: "#8A5A00",
  web: "#6B4FB3", // facts from the web or the press: less trusted
  right: "#1F7A4D",
  wrong: "#B4421A",
  abstain: "#9AA3B2",
} as const;

export const font = { body: '"Atkinson Hyperlegible Next", system-ui, sans-serif' } as const;
export const size = { xs: 12, sm: 14, md: 16, lg: 20, xl: 28, xxl: 40, hero: 54 } as const;
export const weight = { regular: 400, medium: 500, bold: 700, black: 800 } as const;
export const space = [0, 4, 8, 12, 16, 24, 32, 48, 64, 96] as const;
export const radius = { sm: 4, md: 10, pill: 999 } as const;
export const measure = { text: 68, page: 1180, bar: 14, node: { w: 210, h: 54 }, level: 110, chart: 420 } as const;
export const breakpoint = { narrow: 640 } as const;
export const motion = { fast: 0.2, step: 0.06, ease: [0.22, 1, 0.36, 1] as const } as const;
