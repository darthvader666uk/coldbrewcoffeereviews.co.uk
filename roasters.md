---
layout: page
permalink: /roasters/
title: UK Speciality Coffee Roasters
description: "26 UK speciality coffee roasters, Welsh roasters first, with where they roast and a direct link to buy their beans. Every one is watched for new coffees and restocks."
---
{%- assign roasters = site.data.roasters -%}
{%- assign areas = roasters | map: "area" | uniq -%}

<p class="intro">Where to buy fresh coffee beans, straight from the people who roast them. These are the {{ roasters.size }} UK speciality coffee roasters the Last Shift Coffee Drops bot keeps an eye on, starting with the Welsh ones.</p>
<p>Every name links straight to the roaster's own shop. Where I've reviewed one of their coffees, the review is linked too. New coffees and restocks from all of them go up every Friday in the <a href="{{ '/drops/' | relative_url }}">Coffee Drops</a> roundup.</p>

{% for area in areas -%}
<h2>Coffee roasters in {{ area }}</h2>
<ul class="roaster-list">
{%- for r in roasters %}{% if r.area == area %}
  <li><a href="{{ r.url }}" target="_blank" rel="noopener">{{ r.name }}</a>, {{ r.town }}
  {%- if r.reviewed_as %}{% assign reviews = site.posts | where: "roaster", r.reviewed_as %}{% for p in reviews %} &middot; <a href="{{ p.url | relative_url }}">{{ p.title }}</a>{% endfor %}{% endif %}</li>
{%- endif %}{% endfor %}
</ul>
{% endfor %}

<h2>Missing a roaster?</h2>
<p>Pop it in #roaster-requests on the <a href="https://discord.gg/xzEjd4888q" target="_blank" rel="noopener">Last Shift Coffee Discord</a>. The bot can only read shops that run on Shopify (most of them do), but I'll add any I can.</p>

<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "ItemList",
  "name": "UK speciality coffee roasters",
  "numberOfItems": {{ roasters.size }},
  "itemListElement": [
  {%- for r in roasters %}
    { "@type": "ListItem", "position": {{ forloop.index }}, "item": {
      "@type": "Organization", "name": {{ r.name | jsonify }}, "url": {{ r.url | jsonify }},
      "address": { "@type": "PostalAddress", "addressLocality": {{ r.town | jsonify }}, "addressRegion": {{ r.area | jsonify }}, "addressCountry": "GB" } } }{% unless forloop.last %},{% endunless %}
  {%- endfor %}
  ]
}
</script>
