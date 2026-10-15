-- Import to MMT: replace the watchlist in the open MMT tab with a TradingView watchlist export.
-- Runs openmarket-wrun/mmt/tv_watchlist_import.py (preview first, then replace on confirmation).
set py to "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
set importer to "/Users/Shared/Projects/stable-workshop/openmarket-wrun/mmt/tv_watchlist_import.py"
try
	set f to choose file with prompt "TradingView watchlist to import into MMT" of type {"txt", "public.plain-text"} default location (path to downloads folder)
on error
	return
end try
set p to POSIX path of f
set cmd to quoted form of py & " " & quoted form of importer & " " & quoted form of p & " --summary"
try
	set preview to do shell script cmd & " --dry-run 2>&1"
on error e
	display dialog "Could not read the watchlist:" & return & return & e buttons {"OK"} default button "OK" with title "Import to MMT" with icon stop
	return
end try
try
	display dialog preview & return & return & "Replace the watchlist in your open MMT tab with these markets?" buttons {"Cancel", "Replace"} default button "Replace" cancel button "Cancel" with title "Import to MMT"
on error
	return
end try
try
	set result_text to do shell script cmd & " 2>&1"
	display dialog result_text buttons {"OK"} default button "OK" with title "Import to MMT"
on error e
	display dialog "Import failed:" & return & return & e & return & return & "Is MMT open in your browser?" buttons {"OK"} default button "OK" with title "Import to MMT" with icon stop
end try
