-- Agent monteur - Pont (interface web)
-- Lance le pont local qui relie ton interface web (Base44) à l'agent. Laisse la fenêtre noire ouverte.
-- Installation : copie ce fichier dans le dossier Scripts/Utility de DaVinci Resolve, puis redémarre Resolve.
-- Si ton agent n'est pas dans C:\agent, change la ligne ci-dessous.
local pont = "C:\\agent\\pont_agent.py"

local commande = 'start "Pont agent monteur" cmd /k py -3 "' .. pont .. '"'
os.execute(commande)
