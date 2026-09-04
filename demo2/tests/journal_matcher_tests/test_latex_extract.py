from journal_matcher.latex_extract import extract_manuscript, extract_text


def test_extracts_structure_and_custom_theorem_environment():
    source = r"""
\title{A Small Result}
\begin{abstract}We prove a useful bound.\end{abstract}
\newtheorem{mainresult}{Main Result}
\section{Introduction}
The introduction explains the contribution.
\begin{mainresult}\label{thm:main}
For every $n$, the bound holds.
\end{mainresult}
\section{Conclusion}
This completes the argument.
\begin{thebibliography}{9}
\bibitem{one} A. Author, A paper, DOI: 10.1234/example.
\end{thebibliography}
"""
    manuscript = extract_text(source)
    assert manuscript.title == "A Small Result"
    assert "useful bound" in manuscript.abstract
    assert manuscript.sections == ["Introduction", "Conclusion"]
    assert manuscript.theorems[0].result_id == "thm:main"
    assert "For every" in manuscript.theorems[0].statement
    assert manuscript.bibliography[0]["doi"] == "10.1234/example."


def test_missing_abstract_uses_post_abstract_content_as_introduction():
    manuscript = extract_text(r"\title{No Abstract}\section{Results}The result is here.")
    assert manuscript.title == "No Abstract"
    assert manuscript.introduction


def test_extracts_section_bodies_proofs_and_local_includes(tmp_path):
    (tmp_path / "methods.tex").write_text(
        r"""\section{Methods}
We use a counting argument.
\begin{proof}The counting argument is given here.\end{proof}""",
        encoding="utf-8",
    )
    main = tmp_path / "main.tex"
    main.write_text(r"""\title{A Multi-file Article}
\begin{abstract}A short abstract.\end{abstract}
\input{methods}
\section{Conclusion}The result follows.""", encoding="utf-8")

    manuscript = extract_manuscript(main)
    assert manuscript.sections == ["Methods", "Conclusion"]
    assert manuscript.section_contents[0]["title"] == "Methods"
    assert "counting argument" in manuscript.section_contents[0]["text"]
    assert manuscript.proofs[0]["proof_id"] == "proof-1"
