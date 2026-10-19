(function () {
  window.ResearchPalette = ['#35688e','#8b652e','#2b685a','#665184','#9a4f4f','#526675','#73733c','#784e64'];
  const profiles = window.CompanyProfileData || {};
  const key = ticker => String(ticker).trim().toUpperCase().replace(/\.OL$/, '');
  window.CompanyProfiles = {
    name(ticker) { return profiles[key(ticker)]?.name || ''; },
    render(ticker) {
      const panel = document.getElementById('company-profile');
      panel.replaceChildren();
      const add = (tag, text, className) => { const node=document.createElement(tag); node.textContent=text; if(className) node.className=className; panel.append(node); return node; };
      const link = (parent, text, url) => {
        if (!url || !/^https:\/\//.test(url)) return;
        const node=document.createElement('a'); node.href=url; node.textContent=text; node.target='_blank'; node.rel='noopener noreferrer'; parent.append(node);
      };
      const profile=profiles[key(ticker)];
      document.getElementById('instrument-name').textContent=profile?.name || ticker;
      document.getElementById('instrument-symbol').textContent=ticker;
      add('p','COMPANY PROFILE','eyebrow');
      add('h2',profile ? `${profile.name} · ${ticker}` : ticker);
      if (!profile) {
        add('p','This ticker is not in the current company directory. Its profile needs to be added before company details can be displayed.');
        return;
      }
      add('p',profile.description);
      const facts=document.createElement('dl'); facts.className='profile-facts';
      for (const [label,value] of [['Industry / business',profile.industry],['Sector',profile.sector],['Country',profile.country],['Founded',profile.founded],['Share class',profile.share_class],['Dataset ticker',ticker]]) {
        if (!value) continue;
        const group=document.createElement('div'),term=document.createElement('dt'),definition=document.createElement('dd');
        term.textContent=label; definition.textContent=value; group.append(term,definition); facts.append(group);
      }
      panel.append(facts);
      link(add('p','','profile-homepage'),'Company homepage ↗',profile.homepage);
      const source=add('p',`Directory snapshot: ${profile.retrieved} · `,'profile-source');
      link(source,'Profile data source ↗',profile.source);
      if (profile.description_source) link(add('p','','profile-source'),'Business description source ↗',profile.description_source);
      if (profile.share_source) link(add('p','','profile-source'),'Share-class information ↗',profile.share_source);
      if (profile.note) add('p',profile.note,'profile-source');
      add('p',`${profile.classification}. Descriptive company information; not a valuation or confirmation of current listing status.`,'profile-source');
    }
  };
})();
