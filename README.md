# Scripts
General purpose scripts


## getdoc.py

Script which downloads & formats an online text (article, blogpost) for printing / easier reading.

Uses pandoc, BeautifulSoup and exiftool. Can produce most formats that pandoc can output to (PDF, HTML, DOCX, EPUB, ODT,
RTF, etc.), MHT (custom generator) or ZIP archive of HTML + images.

Sample usage: `getdoc.py http://some.website.com/some-awesome-article-or-blogpost -o pdf`

See the script header for installation instructions.

