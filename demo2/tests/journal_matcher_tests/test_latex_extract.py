from journal_matcher.latex_extract import extract_text


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
