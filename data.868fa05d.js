const artist = {
  name: "Sustancia 'X'",
  avatar: "assets/profile.avif",
};

function buildArtSources(path) {
  if (!path) {
    return null;
  }

  const match = path.match(/^(.*)\.avif$/i);
  if (!match) {
    return {
      src: path,
      srcSet: path,
      preload: path,
    };
  }

  const [, base] = match;

  return {
    src: `${base}.avif`,
    srcSet: `${base}-320.avif 320w, ${base}.avif 640w`,
    preload: `${base}.avif`,
  };
}

function buildResponsivePictureHTML(artSources, alt, sizes, options = {}) {
  if (!artSources) {
    return `<div class="placeholder-art">🎵</div>`;
  }

  const {
    className = "",
    loading = "lazy",
    decoding = "async",
    fetchPriority = "",
    onerror = "",
    ariaHidden = false,
  } = options;

  const classAttr = className ? ` class="${className}"` : "";
  const loadingAttr = loading ? ` loading="${loading}"` : "";
  const decodingAttr = decoding ? ` decoding="${decoding}"` : "";
  const fetchPriorityAttr = fetchPriority ? ` fetchpriority="${fetchPriority}"` : "";
  const onerrorAttr = onerror ? ` onerror="${onerror}"` : "";
  const ariaHiddenAttr = ariaHidden ? ` aria-hidden="true"` : "";

  return `
    <img src="${artSources.src}" srcset="${artSources.srcSet}" sizes="${sizes}" alt="${alt}"${classAttr}${loadingAttr}${decodingAttr}${fetchPriorityAttr}${ariaHiddenAttr}${onerrorAttr} />
  `;
}

const songs = [
  {
    id: "chula",
    title: "Chula",
    subtitle: "Single · 2026",
    art: "assets/chula.avif",
    color: "#2986c4", // accent glow color per track
    links: {
      spotify: "https://open.spotify.com/track/2lMphaJlJYAzvwq1IWuiEL?si=f6c534927ee743dd",
      apple: "https://music.apple.com/us/album/chula/6783310835?i=6783310836",
      youtube: "https://www.youtube.com/watch?v=OIl0u1YprD0",
    },
  },
  {
    id: "ella-me-vio",
    title: "Ella Me Vio",
    subtitle: "Single · 2025",
    art: "assets/ella-me-vio.avif",
    color: "#7c3aed", // accent glow color per track
    links: {
      spotify: "https://open.spotify.com/album/0wf1GzzxEbJC8o3D2GVREU?si=tSYrvB3dSXqGwxGM7hz-Hw",
      apple: "https://music.apple.com/us/album/ella-me-vio/1845122459?i=1845122460",
      youtube: "https://www.youtube.com/watch?v=A04JqK3OkSM",
    },
  },
  {
    id: "artificial",
    title: "Artificial",
    subtitle: "Single · 2024",
    art: "assets/artificial.avif",
    color: "#7c3aed", // accent glow color per track
    links: {
      spotify: "https://open.spotify.com/album/5mQTyAXW9pDZBIGRLWcLan?si=FAoXCO87Rfu5X1jrf9clQA",
      apple: "https://music.apple.com/us/album/artificial-single/1770760767?i=1722199974",
      youtube: "https://www.youtube.com/watch?v=Caz3HBqcpEY",
    },
  },
  {
    id: "weekencito",
    title: "Weekencito",
    subtitle: "Single · 2024",
    art: "assets/weekencito.avif",
    color: "#a84545",
    links: {
      spotify: "https://open.spotify.com/album/0fqGL7aWCZjeB5vR5meDV6?si=XLEScrsjQtiLJ_q1qUwQ4Q",
      apple: "https://music.apple.com/us/album/weekencito/1750909020?i=1750909021",
      youtube: "https://www.youtube.com/watch?v=T9IKjVskkfo",
    },
  },
  {
    id: "una-vez-mas",
    title: "Una Vez Más",
    subtitle: "Single · 2023",
    art: "assets/una-vez-mas.avif",
    color: "#becfd3",
    links: {
      spotify: "https://open.spotify.com/album/5F3rXzONU01fNqSVFydwui?si=idaEC31yTMari5OOzZGrjw",
      apple: "https://music.apple.com/us/album/una-vez-m%C3%A1s/1722199973?i=1722199974",
      youtube: "https://www.youtube.com/watch?v=eD4sAIgguXE",
    },
  },
  {
    id: "no-quiere",
    title: "No Quiere",
    subtitle: "Single · 2023",
    art: "assets/no-quiere.avif",
    color: "#0891b2",
    links: {
      spotify: "https://open.spotify.com/album/6QLJy2RXJ8JX461wgzhGlL?si=B_P0KfJHRjC4J6O-mmiuJw",
      apple: "https://music.apple.com/us/album/no-quiere/1711391044?i=1711391046",
      youtube: "https://www.youtube.com/watch?v=LNy9tKKXeVk",
    },
  },
  {
    id: "llegar",
    title: "Llegar",
    subtitle: "Single · 2023",
    art: "assets/llegar.avif",
    color: "#dda867",
    links: {
      spotify: "https://open.spotify.com/album/2XHCUhQFIw1F98azKbdH63?si=YqPRMk-CQsyh-hwBKKRimQ",
      apple: "https://music.apple.com/us/album/llegar/1698894916?i=1698894917",
      youtube: "https://www.youtube.com/watch?v=w0wnKhFXh50",
    },
  },
  {
    id: "en-mi-mente",
    title: "En Mi Mente",
    subtitle: "Single · 2023",
    art: "assets/en-mi-mente.avif",
    color: "#dc2626",
    links: {
      spotify: "https://open.spotify.com/album/3rvnfN3MNbUHLXMtfcJ8qO?si=fmjMATjfQL6Xs97lyxsVhw",
      apple: "https://music.apple.com/us/album/en-mi-mente/1694260538?i=1694260540",
      youtube: "https://www.youtube.com/watch?v=kPXbzPHYLp0",
    },
  },
];

songs.forEach(song => {
  song.artSources = buildArtSources(song.art);
});
