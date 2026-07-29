import{u as c,j as e,ai as l,a4 as m,T as a}from"./main-DHi_zKps.js";import{F as d}from"./file-text-DCmbUh18.js";import"./preload-helper-ckwbz45p.js";import"./backend-D5a3Te7D.js";const u=`
## ⚠️ NON-EMERGENCY SERVICE ONLY

**This is a NON-EMERGENCY service request system.**

**For emergencies, call 911 immediately.**

This includes but is not limited to:
- Medical emergencies
- Fires
- Crimes in progress
- Immediate threats to life or property
- Downed power lines
- Gas leaks

Do NOT use this system for urgent matters that require immediate response.

---

## Service Description

This 311 portal provides a convenient way for residents to submit non-emergency service requests to your municipal government. Common request types include:

- Pothole repairs
- Streetlight outages
- Graffiti removal
- Missed trash collection
- Code enforcement concerns
- Parks and facilities maintenance
- General municipal inquiries

## User Responsibilities

By using this service, you agree to:

- **Provide Accurate Information**: Submit truthful and accurate information in your requests
- **Use Appropriately**: Use this service only for legitimate municipal service requests
- **No Abuse**: Not submit false, fraudulent, or malicious requests
- **Respect Staff**: Communicate respectfully with municipal staff
- **Emergency Protocol**: Call 911 for any emergency situations

## Service Limitations

- **No Guaranteed Response Time**: While we strive to address requests promptly, response times vary based on priority, resources, and request volume
- **Municipal Jurisdiction Only**: We can only address issues within municipal jurisdiction
- **Third-Party Issues**: We cannot resolve issues related to private property, utilities managed by other entities, or matters outside municipal control
- **Resource Availability**: Services are subject to available resources and staffing

## Request Processing

- Requests are reviewed and routed to the appropriate department
- You may receive status updates if contact information was provided
- Request status can be tracked using your confirmation number
- Some requests may require additional information or inspection

## Disclaimer of Warranties

This service is provided "as is" without warranties of any kind. The municipality:

- Does not guarantee uninterrupted service availability
- Does not guarantee resolution of all reported issues
- Is not liable for issues arising from delayed responses
- Reserves the right to prioritize requests based on public safety and available resources

## Limitation of Liability

To the fullest extent permitted by law, the municipality shall not be liable for:

- Indirect, incidental, or consequential damages
- Issues arising from information provided by users
- Delays in addressing service requests
- Actions taken by third-party contractors

## Modifications

We reserve the right to modify these terms at any time. Continued use of the service constitutes acceptance of modified terms.

## Governing Law

These terms are governed by applicable state and local laws. Any disputes shall be resolved in accordance with the municipality's existing policies and procedures.

## Contact

For questions about this service or these terms, please contact your municipal clerk or the appropriate department.

---

*By submitting a service request, you acknowledge that you have read and agree to these terms.*
`;function y(){const{settings:r}=c(),o=(r==null?void 0:r.terms_of_service)||u,n=(r==null?void 0:r.township_name)||"Your Municipality";return e.jsxs("div",{className:"min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900",children:[e.jsx("header",{className:"glass-sidebar border-b border-white/10",children:e.jsxs("div",{className:"max-w-4xl mx-auto px-4 py-4 flex items-center gap-4",children:[e.jsx(l,{to:"/",className:"p-2 rounded-lg hover:bg-white/10 transition-colors","aria-label":"Back to home",children:e.jsx(m,{className:"w-5 h-5 text-white/70"})}),e.jsxs("div",{className:"flex items-center gap-3",children:[e.jsx("div",{className:"w-10 h-10 rounded-xl bg-amber-500/20 flex items-center justify-center",children:e.jsx(d,{className:"w-5 h-5 text-amber-400"})}),e.jsxs("div",{children:[e.jsx("h1",{className:"text-xl font-bold text-white",children:"Terms of Service"}),e.jsxs("p",{className:"text-sm text-white/50",children:[n," 311 Service"]})]})]})]})}),e.jsx("div",{className:"bg-red-500/20 border-b border-red-500/30",children:e.jsxs("div",{className:"max-w-4xl mx-auto px-4 py-3 flex items-center gap-3",children:[e.jsx(a,{className:"w-5 h-5 text-red-400 flex-shrink-0"}),e.jsxs("p",{className:"text-red-200 text-sm",children:[e.jsx("strong",{children:"This is NOT for emergencies."})," For police, fire, or medical emergencies, call ",e.jsx("strong",{children:"911"})," immediately."]})]})}),e.jsxs("main",{className:"max-w-4xl mx-auto px-4 py-8",children:[e.jsx("div",{className:"glass-card rounded-2xl p-8",children:e.jsx("div",{className:"prose prose-invert prose-sm max-w-none",children:o.split(`
`).map((s,t)=>{if(s.startsWith("## ⚠️"))return e.jsx("div",{className:"bg-red-500/10 border border-red-500/30 rounded-xl p-4 mb-6",children:e.jsxs("h2",{className:"text-xl font-bold text-red-400 flex items-center gap-2",children:[e.jsx(a,{className:"w-6 h-6"}),s.replace("## ⚠️ ","")]})},t);if(s.startsWith("## "))return e.jsx("h2",{className:"text-xl font-bold text-white mt-8 mb-4",children:s.replace("## ","")},t);if(s.startsWith("### "))return e.jsx("h3",{className:"text-lg font-semibold text-white/90 mt-6 mb-3",children:s.replace("### ","")},t);if(s.startsWith("- **")){const i=s.match(/- \*\*(.+?)\*\*: (.+)/);if(i)return e.jsxs("li",{className:"text-white/70 ml-4 my-1",children:[e.jsxs("strong",{className:"text-white",children:[i[1],":"]})," ",i[2]]},t)}return s.startsWith("- ")?e.jsx("li",{className:"text-white/70 ml-4 my-1",children:s.replace("- ","")},t):s.startsWith("**")&&s.endsWith("**")?e.jsx("p",{className:"text-white font-semibold my-2",children:s.replace(/\*\*/g,"")},t):s.startsWith("*")&&s.endsWith("*")?e.jsx("p",{className:"text-white/50 italic text-sm my-4",children:s.replace(/\*/g,"")},t):s==="---"?e.jsx("hr",{className:"border-white/10 my-8"},t):s.trim()?e.jsx("p",{className:"text-white/70 my-3",children:s},t):null})})}),e.jsxs("p",{className:"text-center text-white/30 text-sm mt-8",children:["Last updated: ",new Date().toLocaleDateString()]})]})]})}export{y as default};
