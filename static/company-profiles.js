/* Descriptive snapshots, reviewed against the linked company sources on 2026-10-19.
   Business categories are editorial descriptions, not an exchange classification. */
(function () {
  window.ResearchPalette = ['#35688e','#8b652e','#2b685a','#665184','#9a4f4f','#526675','#73733c','#784e64'];
  const profiles = {
    VEI: ['Veidekke', 'Construction', 'Scandinavia', 'Builds roads, tunnels, bridges and buildings across Scandinavia. Its origins are in Norwegian road construction.', 'https://www.veidekke.com/about-veidekke/'],
    NRC: ['NRC Group', 'Rail and civil infrastructure', 'Norway, Sweden and Finland', 'Engineers, builds and maintains transport infrastructure. Its activities include rail construction and maintenance, civil works and specialist infrastructure services.', 'https://www.nrcgroup.com/about-us'],
    EQNR: ['Equinor', 'Energy', 'International', 'Produces oil and gas and develops renewable power and low-carbon energy projects. The Norwegian continental shelf is central to its operations, alongside international energy assets.', 'https://www.equinor.com/about-us'],
    DNB: ['DNB', 'Financial services', 'Norway and international markets', 'A Norwegian financial services group serving personal and business customers, with banking and related financial services.', 'https://m.dnb.no/en/about-us/about-dnb.html'],
    MOWI: ['Mowi', 'Seafood and salmon farming', 'International', 'Produces farmed Atlantic salmon and other seafood products for international markets.', 'https://mowi.com/about-us/'],
    TEL: ['Telenor', 'Telecommunications and technology', 'Nordics and Asia', 'Provides telecommunications and technology services across Nordic and Asian markets.', 'https://www.telenor.com/who-we-are/'],
    NHY: ['Norsk Hydro', 'Aluminium and renewable energy', 'International', 'Operates aluminium and renewable energy businesses, including activities supporting aluminium production and recycling.', 'https://www.hydro.com/en/global/about-hydro/our-purpose-and-values/'],
    YAR: ['Yara International', 'Crop nutrition and ammonia', 'International', 'Supplies crop nutrition and ammonia products. Its agricultural offering combines fertilizers, agronomic knowledge and digital farming tools.', 'https://www.yara.com/this-is-yara/']
  };
  const key = ticker => String(ticker).trim().toUpperCase().replace(/\.OL$/, '');
  window.CompanyProfiles = {
    name(ticker) { return profiles[key(ticker)]?.[0] || ''; },
    render(ticker) {
      const panel = document.getElementById('company-profile');
      panel.replaceChildren();
      const add = (tag, text, className) => { const node = document.createElement(tag); node.textContent = text; if(className) node.className = className; panel.append(node); return node; };
      const profile = profiles[key(ticker)];
      add('p', 'COMPANY PROFILE', 'eyebrow');
      add('h2', profile ? `${profile[0]} · ${ticker}` : ticker);
      if (!profile) {
        add('p', 'A source-reviewed company profile is not yet available for this ticker. Price history and model results below remain available.');
        add('p', 'Profile coverage: VEI, NRC, EQNR, DNB, MOWI, TEL, NHY and YAR. Search by company name or ticker to explore these profiles.', 'profile-source');
        return;
      }
      add('p', profile[3]);
      const facts = document.createElement('dl'); facts.className = 'profile-facts';
      for (const [label, value] of [['Business', profile[1]], ['Operating markets', profile[2]], ['Dataset ticker', ticker]]) {
        const group=document.createElement('div'), term=document.createElement('dt'), definition=document.createElement('dd');
        term.textContent=label; definition.textContent=value; group.append(term,definition); facts.append(group);
      }
      panel.append(facts);
      const source=add('p', 'Reviewed 19 October 2026 · ', 'profile-source');
      const link=document.createElement('a'); link.href=profile[4]; link.textContent='Company source ↗'; link.target='_blank'; link.rel='noopener noreferrer'; source.append(link);
      const homepage=add('p', '', 'profile-homepage');
      const homeLink=document.createElement('a');
      homeLink.href=key(ticker)==='DNB'?'https://www.dnb.no/':new URL(profile[4]).origin+'/';
      homeLink.textContent='Company homepage ↗'; homeLink.target='_blank'; homeLink.rel='noopener noreferrer'; homepage.append(homeLink);
      add('p', 'Descriptive company snapshot; business categories are editorial. Financial statements and valuation metrics are not included.', 'profile-source');
    }
  };
})();
