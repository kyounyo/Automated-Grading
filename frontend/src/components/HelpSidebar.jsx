import React, { useState } from 'react';
import { HelpCircle, X, ChevronDown, ChevronUp } from 'lucide-react';
import { useLocation } from 'react-router-dom';

const PAGE_HELP = {
  '/': {
    title: 'Dashboard',
    intro: 'This is your grading command centre. At a glance, you can see how marking is progressing for the current assignment.',
    sections: [
      {
        heading: '📊 The summary cards',
        body: 'The coloured cards at the top show totals for submissions, graded papers, flagged papers (that need your attention), and the class average score.',
      },
      {
        heading: '⚠️ Flagged papers',
        body: 'Flagged means the AI is uncertain about a score, or two AI systems disagreed with each other. You should review these manually before finalising grades.',
      },
      {
        heading: '📈 Score distribution chart',
        body: 'This bar chart shows how many students scored in each mark range. It helps you spot if too many students are failing or if marking looks unusually generous.',
      },
      {
        heading: '🚀 Grade All Pending button',
        body: 'Click this to start the AI grading process for all uploaded submissions that haven\'t been graded yet. You can track progress in real-time.',
      },
    ],
  },
  '/create-assignment': {
    title: 'Create Assignment',
    intro: 'Set up a new assignment by giving it a name, uploading your marking scheme, and reviewing the questions the system detected.',
    sections: [
      {
        heading: '📝 Step 1 — Assignment details',
        body: 'Fill in your course code (e.g. PHR1021) and give the assignment a clear title so you can recognise it later.',
      },
      {
        heading: '📂 Step 2 — Upload your marking scheme',
        body: 'Upload an Excel (.xlsx) or CSV file containing your questions, model answers, and maximum marks. The system will automatically read the columns — don\'t worry if the column headings are slightly different, it\'s flexible.',
      },
      {
        heading: '✅ Step 3 — Review parsed questions',
        body: 'After uploading, the system shows what it understood from your file. Check each question and model answer carefully. You can edit them here before saving.',
      },
      {
        heading: '💡 Calibration tip',
        body: 'Calibration is optional but recommended. It lets you upload a few of your own hand-marked examples so the AI matches your strictness level.',
      },
    ],
  },
  '/bulk-upload': {
    title: 'Upload Student Submissions',
    intro: 'Upload the file containing your students\' answers. The system supports Excel and CSV files.',
    sections: [
      {
        heading: '📋 What format does the file need to be?',
        body: 'The file should have columns for student ID, student name, and their answers per question. The system is flexible with column names — "Student ID", "Matric No", "Candidate ID" all work.',
      },
      {
        heading: '🔄 Uploading again',
        body: 'If you upload a file a second time for the same assignment, existing student records will be updated — you won\'t get duplicates.',
      },
      {
        heading: '🎯 Calibration samples',
        body: 'You can mark some submissions as "calibration samples" — these are papers you will grade yourself to teach the AI your marking standard.',
      },
    ],
  },
  '/submissions': {
    title: 'Submissions List',
    intro: 'See all student submissions for the current assignment, their AI-assigned scores, confidence levels, and grading status.',
    sections: [
      {
        heading: '🟢 Graded — what does it mean?',
        body: 'The AI graded this paper and both AI agents agreed on the score. It\'s ready for your approval.',
      },
      {
        heading: '🟡 Flagged — why is it yellow?',
        body: 'The two AI systems disagreed on the score, or the AI wasn\'t confident. These papers need your manual review before they\'re finalised.',
      },
      {
        heading: '🔵 Confidence score',
        body: 'A percentage showing how sure the system is about the grade. Below 75%, the paper is flagged for your review. 95% is the maximum — the system is never overconfident.',
      },
      {
        heading: '▶️ Grade individual papers',
        body: 'Click the "Grade" button on any pending paper to run AI grading just for that student.',
      },
    ],
  },
  '/calibration': {
    title: 'Calibration Setup',
    intro: 'Calibration teaches the AI to match your marking style. It\'s optional but recommended — it only needs to be done once per assignment.',
    sections: [
      {
        heading: '🎯 What is calibration?',
        body: 'You provide a few papers you\'ve already marked yourself. The AI reads your marks and learns your strictness, partial-credit decisions, and style before grading the rest of the class.',
      },
      {
        heading: '📥 Option 1 — Import existing grades',
        body: 'If you\'ve already graded some papers (e.g. in a spreadsheet), upload them here. The system will extract your scores as calibration examples.',
      },
      {
        heading: '📖 Option 2 — Mark samples here',
        body: 'Open a sample paper and grade it yourself inside the system. Click "Save Example" per question. The AI uses these as its reference standard.',
      },
      {
        heading: '🎚️ Flagging Sensitivity',
        body: 'The slider controls how often papers get sent to you for review. "Strict" flags more papers; "Lenient" flags fewer. Start with Medium and adjust based on how many reviews feel manageable.',
      },
    ],
  },
  '/review': {
    title: 'Grading Review',
    intro: 'Review the AI\'s grading for one student at a time. You can read their answers, see what the AI thought, and adjust the score if needed.',
    sections: [
      {
        heading: '📖 Reading the student\'s answers',
        body: 'The left panel shows the student\'s raw answers, with highlighted sections showing what the AI paid attention to.',
      },
      {
        heading: '✏️ Adjusting scores',
        body: 'You can change the score for each question individually using the +/- buttons, or type a new total score in the box at the bottom. All changes are logged.',
      },
      {
        heading: '✅ Approving a grade',
        body: 'Click "Approve Grade" to confirm the AI\'s score is correct. This removes the flag and marks the paper as finalised.',
      },
      {
        heading: '⚠️ Why is this paper flagged?',
        body: 'The flag reason card explains in plain language why this paper needs attention — e.g., two AIs disagreed, or the answer was very short.',
      },
    ],
  },
};

const FAQ_ITEMS = [
  {
    q: 'Is the AI always right?',
    a: 'No — the AI is a first-pass grading assistant. You should always review flagged papers, and spot-check graded ones. The system is designed to save you time, not replace your judgment.',
  },
  {
    q: 'What is calibration?',
    a: 'Calibration is where you provide a few of your own hand-marked examples. The AI then uses these to match your marking strictness and style for the rest of the batch.',
  },
  {
    q: 'How is confidence calculated?',
    a: 'Confidence is based on how closely two independent AI systems agreed on the score, the length of the student\'s answer, and whether their scoring matched question-by-question. It\'s a formula — not just the AI guessing.',
  },
  {
    q: 'Can I change a grade after approving?',
    a: 'Yes. You can override any score at any time from the Grading Review page. Every change is logged in an audit trail.',
  },
];

const AccordionItem = ({ question, answer }) => {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ borderBottom: '1px solid var(--border-light)', paddingBottom: '0.5rem' }}>
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          background: 'none', border: 'none', cursor: 'pointer',
          width: '100%', textAlign: 'left', padding: '0.55rem 0',
          display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '0.5rem'
        }}
      >
        <span style={{ fontSize: '0.82rem', fontWeight: 600, color: 'var(--secondary)', lineHeight: 1.4 }}>{question}</span>
        {open ? <ChevronUp size={14} color="var(--text-muted)" style={{ flexShrink: 0, marginTop: 2 }} /> : <ChevronDown size={14} color="var(--text-muted)" style={{ flexShrink: 0, marginTop: 2 }} />}
      </button>
      {open && (
        <p style={{ margin: '0 0 0.5rem 0', fontSize: '0.8rem', color: 'var(--text-muted)', lineHeight: 1.6 }}>{answer}</p>
      )}
    </div>
  );
};

const HelpSidebar = () => {
  const [open, setOpen] = useState(false);
  const location = useLocation();

  // Match by exact path or prefix
  const matchedKey = Object.keys(PAGE_HELP).find(k =>
    k === location.pathname || (k !== '/' && location.pathname.startsWith(k))
  ) || '/';

  const help = PAGE_HELP[matchedKey] || PAGE_HELP['/'];

  return (
    <>
      {/* Floating ? button */}
      <button
        id="help-sidebar-trigger"
        onClick={() => setOpen(true)}
        title="Help & Guide"
        style={{
          position: 'fixed',
          bottom: '1.75rem',
          right: '1.75rem',
          width: '44px',
          height: '44px',
          borderRadius: '50%',
          backgroundColor: 'var(--primary)',
          color: '#fff',
          border: 'none',
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 1000,
          transition: 'background-color 150ms ease, transform 150ms ease',
        }}
        onMouseEnter={e => { e.currentTarget.style.backgroundColor = 'var(--primary-hover)'; e.currentTarget.style.transform = 'scale(1.08)'; }}
        onMouseLeave={e => { e.currentTarget.style.backgroundColor = 'var(--primary)'; e.currentTarget.style.transform = 'scale(1)'; }}
      >
        <HelpCircle size={22} />
      </button>

      {/* Overlay */}
      {open && (
        <div
          onClick={() => setOpen(false)}
          style={{
            position: 'fixed', inset: 0, backgroundColor: 'rgba(0,0,0,0.25)',
            zIndex: 1001, backdropFilter: 'blur(2px)'
          }}
        />
      )}

      {/* Slide-in drawer */}
      <div
        style={{
          position: 'fixed',
          top: 0,
          right: 0,
          bottom: 0,
          width: '340px',
          backgroundColor: 'var(--surface)',
          borderLeft: '1px solid var(--border)',
          zIndex: 1002,
          display: 'flex',
          flexDirection: 'column',
          transform: open ? 'translateX(0)' : 'translateX(100%)',
          transition: 'transform 300ms cubic-bezier(0.16, 1, 0.3, 1)',
          overflowY: 'hidden',
        }}
      >
        {/* Header */}
        <div style={{
          padding: '1.1rem 1.25rem',
          borderBottom: '1px solid var(--border)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexShrink: 0,
          backgroundColor: 'var(--primary-light)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <HelpCircle size={18} color="var(--primary)" />
            <span style={{ fontWeight: 700, fontSize: '0.95rem', color: 'var(--secondary)' }}>
              Help — {help.title}
            </span>
          </div>
          <button
            onClick={() => setOpen(false)}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)', display: 'flex', padding: '4px' }}
          >
            <X size={18} />
          </button>
        </div>

        {/* Scrollable body */}
        <div style={{ overflowY: 'auto', flex: 1, padding: '1.25rem' }}>
          {/* Intro */}
          <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)', lineHeight: 1.65, marginBottom: '1.25rem' }}>
            {help.intro}
          </p>

          {/* Sections */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.85rem', marginBottom: '1.5rem' }}>
            {help.sections.map((s, i) => (
              <div key={i} style={{
                padding: '0.8rem 1rem',
                backgroundColor: 'var(--bg-subtle)',
                borderRadius: '8px',
                border: '1px solid var(--border-light)',
              }}>
                <p style={{ margin: '0 0 0.3rem 0', fontWeight: 700, fontSize: '0.835rem', color: 'var(--secondary)' }}>{s.heading}</p>
                <p style={{ margin: 0, fontSize: '0.8rem', color: 'var(--text-muted)', lineHeight: 1.6 }}>{s.body}</p>
              </div>
            ))}
          </div>

          {/* FAQ */}
          <div>
            <p style={{ margin: '0 0 0.65rem 0', fontSize: '0.72rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.07em', color: 'var(--text-dim)' }}>
              Common Questions
            </p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.15rem' }}>
              {FAQ_ITEMS.map((item, i) => (
                <AccordionItem key={i} question={item.q} answer={item.a} />
              ))}
            </div>
          </div>
        </div>

        {/* Footer */}
        <div style={{
          padding: '0.85rem 1.25rem',
          borderTop: '1px solid var(--border)',
          flexShrink: 0,
        }}>
          <p style={{ margin: 0, fontSize: '0.75rem', color: 'var(--text-dim)', textAlign: 'center' }}>
            AutoGrade+ · Academic Assessment Platform
          </p>
        </div>
      </div>
    </>
  );
};

export default HelpSidebar;
