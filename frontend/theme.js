/* Aether Identity design system — extracted verbatim from the Stitch design's tailwind config. */
tailwind.config = {
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        "on-secondary-fixed-variant": "#004e5c", "surface": "#f7f9fb", "outline": "#767586",
        "surface-bright": "#f7f9fb", "on-primary-fixed": "#07006c", "secondary-fixed-dim": "#4cd7f6",
        "on-error": "#ffffff", "secondary-fixed": "#acedff", "secondary-container": "#57dffe",
        "surface-container-high": "#e6e8ea", "inverse-surface": "#2d3133", "primary-fixed": "#e1e0ff",
        "on-secondary-container": "#006172", "surface-container-highest": "#e0e3e5",
        "glass-stroke": "rgba(255, 255, 255, 0.4)", "tertiary-fixed-dim": "#d0bcff",
        "tertiary-container": "#8455ef", "surface-container": "#eceef0", "surface-dim": "#d8dadc",
        "secondary": "#00687a", "on-secondary": "#ffffff", "surface-tint": "#494bd6",
        "primary": "#4648d4", "on-primary-fixed-variant": "#2f2ebe", "error": "#ba1a1a",
        "on-tertiary-fixed": "#23005c", "background": "#f7f9fb", "electric-blue": "#3B82F6",
        "surface-container-lowest": "#ffffff", "tertiary-fixed": "#e9ddff", "on-background": "#191c1e",
        "inverse-primary": "#c0c1ff", "data-node-bg": "#1E293B", "on-tertiary": "#ffffff",
        "on-secondary-fixed": "#001f26", "inverse-on-surface": "#eff1f3", "error-container": "#ffdad6",
        "surface-container-low": "#f2f4f6", "primary-fixed-dim": "#c0c1ff", "primary-container": "#6063ee",
        "outline-variant": "#c7c4d7", "on-tertiary-fixed-variant": "#5516be", "signal-teal": "#14B8A6",
        "on-error-container": "#93000a", "tertiary": "#6b38d4", "on-primary": "#ffffff",
        "surface-variant": "#e0e3e5", "cyber-purple": "#7C3AED", "on-surface": "#191c1e",
        "on-surface-variant": "#464554", "on-tertiary-container": "#fffbff", "on-primary-container": "#fffbff"
      },
      borderRadius: { DEFAULT: "0.25rem", lg: "0.5rem", xl: "0.75rem", full: "9999px" },
      spacing: { gutter: "24px", "margin-desktop": "40px", "margin-mobile": "16px",
                 "container-max": "1280px", unit: "8px" },
      fontFamily: {
        "headline-lg-mobile": ["Plus Jakarta Sans"], "body-lg": ["Inter"], "body-md": ["Inter"],
        "headline-md": ["Plus Jakarta Sans"], "label-mono": ["Inter"], "data-value": ["Inter"],
        "display-lg": ["Plus Jakarta Sans"], "headline-lg": ["Plus Jakarta Sans"]
      },
      fontSize: {
        "headline-lg-mobile": ["28px", { lineHeight: "36px", letterSpacing: "-0.02em", fontWeight: "700" }],
        "body-lg": ["18px", { lineHeight: "28px", fontWeight: "400" }],
        "body-md": ["16px", { lineHeight: "24px", fontWeight: "400" }],
        "headline-md": ["24px", { lineHeight: "32px", letterSpacing: "-0.01em", fontWeight: "600" }],
        "label-mono": ["12px", { lineHeight: "16px", letterSpacing: "0.05em", fontWeight: "600" }],
        "data-value": ["14px", { lineHeight: "20px", fontWeight: "500" }],
        "display-lg": ["48px", { lineHeight: "56px", letterSpacing: "-0.04em", fontWeight: "700" }],
        "headline-lg": ["32px", { lineHeight: "40px", letterSpacing: "-0.02em", fontWeight: "700" }]
      }
    }
  }
};
