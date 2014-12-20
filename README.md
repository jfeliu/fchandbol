fchandbol
=========

Tool to crawl Federació Catalana d'Handbol's website and tweet game scores.

How to use it:

1. Create virtualenv
2. Install dependencies with `pip install -r requirements.txt`
3. Create a twitter account ("https://twitter.com/").
4. Create a twitter app related to your account to get keys and access tokens ("https://apps.twitter.com/").
5. Get game_ids from "http://handbol.playoffinformatica.com/competicio" for each category you are interested in.
6. Put info from previous points 2 and 3 into your local.cfg file which has to have default.cfg format.
7. Run get_results.py

To see game scores follow @resultats_fch on twitter.
