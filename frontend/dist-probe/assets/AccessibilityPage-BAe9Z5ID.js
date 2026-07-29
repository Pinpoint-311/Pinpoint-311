import{c as l,u as o,j as e,ai as d,a4 as m,h as r}from"./main-DHi_zKps.js";import"./preload-helper-ckwbz45p.js";import"./backend-D5a3Te7D.js";/**
 * @license lucide-react v0.468.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const h=l("Accessibility",[["circle",{cx:"16",cy:"4",r:"1",key:"1grugj"}],["path",{d:"m18 19 1-7-6 1",key:"r0i19z"}],["path",{d:"m5 8 3-3 5.5 3-2.36 3.5",key:"9ptxx2"}],["path",{d:"M4.24 14.5a5 5 0 0 0 6.88 6",key:"10kmtu"}],["path",{d:"M13.76 17.5a5 5 0 0 0-6.88-6",key:"2qq6rc"}]]),u=`
## Our Commitment

We are committed to ensuring digital accessibility for all users, including people with disabilities. We continually improve the user experience for everyone and apply the relevant accessibility standards.

## Accessibility Standards

This 311 portal is designed to conform to:

- **WCAG 2.1 Level AA** - Web Content Accessibility Guidelines
- **Section 508** - Federal accessibility requirements
- **ADA** - Americans with Disabilities Act requirements

## Accessibility Features

This portal includes the following accessibility features:

- **Keyboard Navigation**: All functionality is accessible via keyboard
- **Screen Reader Support**: Semantic HTML and ARIA labels for assistive technologies
- **Color Contrast**: Text meets WCAG AA contrast ratios
- **Resizable Text**: Content remains functional when text is resized up to 200%
- **Focus Indicators**: Visible focus states for keyboard navigation
- **Skip Links**: Skip to main content functionality
- **Form Labels**: All form inputs have associated labels
- **Error Identification**: Form errors are clearly identified and described
- **Language**: Page language is properly declared

## Alternative Submission Methods

If you are unable to use this web portal, you can submit service requests via:

- **Phone**: Call 311 or your municipality's main number
- **In Person**: Visit your municipal building during business hours
- **Email**: Contact your municipal clerk

## Known Limitations

We are aware of and working to address:

- Some third-party content may not fully conform to accessibility standards
- Dynamic content updates may require manual refresh for some screen readers
- Map interfaces provide text alternatives but may have limited functionality for some users

## Feedback

We welcome your feedback on the accessibility of this portal. Please let us know if you encounter accessibility barriers:

- Report an accessibility issue through the service request form
- Contact your municipal clerk's office
- Email the IT department

We try to respond to accessibility feedback within 5 business days.

## Continuous Improvement

We conduct regular accessibility audits and training to:

- Identify and remediate accessibility issues
- Train staff on accessibility best practices
- Test with assistive technologies
- Incorporate user feedback

---

*This statement was last reviewed and updated on the date shown below. We regularly review our accessibility practices.*
`;function y(){const{settings:i}=o(),c=(i==null?void 0:i.accessibility_statement)||u,n=(i==null?void 0:i.township_name)||"Your Municipality";return e.jsxs("div",{className:"min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900",children:[e.jsx("header",{className:"glass-sidebar border-b border-white/10",children:e.jsxs("div",{className:"max-w-4xl mx-auto px-4 py-4 flex items-center gap-4",children:[e.jsx(d,{to:"/",className:"p-2 rounded-lg hover:bg-white/10 transition-colors","aria-label":"Back to home",children:e.jsx(m,{className:"w-5 h-5 text-white/70"})}),e.jsxs("div",{className:"flex items-center gap-3",children:[e.jsx("div",{className:"w-10 h-10 rounded-xl bg-emerald-500/20 flex items-center justify-center",children:e.jsx(h,{className:"w-5 h-5 text-emerald-400"})}),e.jsxs("div",{children:[e.jsx("h1",{className:"text-xl font-bold text-white",children:"Accessibility Statement"}),e.jsxs("p",{className:"text-sm text-white/50",children:[n," 311 Service"]})]})]})]})}),e.jsx("div",{className:"bg-emerald-500/20 border-b border-emerald-500/30",children:e.jsxs("div",{className:"max-w-4xl mx-auto px-4 py-3 flex items-center gap-3",children:[e.jsx(r,{className:"w-5 h-5 text-emerald-400 flex-shrink-0"}),e.jsxs("p",{className:"text-emerald-200 text-sm",children:["This portal is designed to meet ",e.jsx("strong",{children:"WCAG 2.1 Level AA"})," accessibility standards."]})]})}),e.jsxs("main",{className:"max-w-4xl mx-auto px-4 py-8",children:[e.jsx("div",{className:"glass-card rounded-2xl p-8",children:e.jsx("div",{className:"prose prose-invert prose-sm max-w-none",children:c.split(`
`).map((t,s)=>{if(t.startsWith("## "))return e.jsx("h2",{className:"text-xl font-bold text-white mt-8 mb-4 first:mt-0",children:t.replace("## ","")},s);if(t.startsWith("### "))return e.jsx("h3",{className:"text-lg font-semibold text-white/90 mt-6 mb-3",children:t.replace("### ","")},s);if(t.startsWith("- **")){const a=t.match(/- \*\*(.+?)\*\*:? ?(.+)?/);if(a)return e.jsxs("li",{className:"text-white/70 ml-4 my-1 flex items-start gap-2",children:[e.jsx(r,{className:"w-4 h-4 text-emerald-400 mt-0.5 flex-shrink-0"}),e.jsxs("span",{children:[e.jsx("strong",{className:"text-white",children:a[1]}),a[2]?`: ${a[2]}`:""]})]},s)}return t.startsWith("- ")?e.jsxs("li",{className:"text-white/70 ml-4 my-1 flex items-start gap-2",children:[e.jsx("span",{className:"text-emerald-400",children:"•"}),e.jsx("span",{children:t.replace("- ","")})]},s):t.startsWith("**")&&t.endsWith("**")?e.jsx("p",{className:"text-white font-semibold my-2",children:t.replace(/\*\*/g,"")},s):t.startsWith("*")&&t.endsWith("*")?e.jsx("p",{className:"text-white/50 italic text-sm my-4",children:t.replace(/\*/g,"")},s):t==="---"?e.jsx("hr",{className:"border-white/10 my-8"},s):t.trim()?e.jsx("p",{className:"text-white/70 my-3",children:t},s):null})})}),e.jsxs("p",{className:"text-center text-white/30 text-sm mt-8",children:["Last updated: ",new Date().toLocaleDateString()]})]})]})}export{y as default};
